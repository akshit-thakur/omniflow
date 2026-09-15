import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlsplit

from scripts import smoke


class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._body = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload).encode("utf-8")
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self._body


class RecordingOpener:
    def __init__(self):
        self.requests = []
        self.urls = []
        self.ai_payload = {
            "status": "healthy",
            "service": "ai",
            "database_available": True,
            "ollama_available": True,
            "index_available": True,
            "index": {"total": 0, "stale": 0},
        }
        self.fail_update = False

    def __call__(self, request, *, timeout):
        method = request.get_method()
        path = urlsplit(request.full_url).path
        headers = {key.lower(): value for key, value in request.header_items()}
        self.requests.append((method, path, headers, timeout))
        self.urls.append(request.full_url)

        if path == "/healthz":
            return FakeResponse(200, {"status": "healthy", "service": "frontend"})
        if path in smoke.INTERNAL_BLOCK_ENDPOINTS:
            return FakeResponse(404, b"<html>not found</html>")
        if path == "/api/ai/health":
            return FakeResponse(200, self.ai_payload)
        if path == "/api/tasks/" and method == "GET":
            return FakeResponse(200, [])
        if path == "/api/tasks/" and method == "POST":
            return FakeResponse(201, {"id": 42, "completed": False})
        if path == "/api/tasks/42" and method == "GET":
            return FakeResponse(200, {"id": 42, "completed": False})
        if path == "/api/tasks/42" and method == "PUT":
            if self.fail_update:
                return FakeResponse(500, {"detail": "forced update failure"})
            return FakeResponse(200, {"id": 42, "completed": True})
        if path == "/api/tasks/42" and method == "DELETE":
            return FakeResponse(200, {"message": "Task deleted successfully"})
        if path in smoke.DOMAIN_LIST_ENDPOINTS:
            return FakeResponse(200, [])
        return FakeResponse(404, {"detail": f"No fake response for {method} {path}"})


class RuntimeConfigurationTests(unittest.TestCase):
    def test_env_file_port_is_used_without_exporting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "OMNIFLOW_PORT=4321\n",
                encoding="utf-8",
            )
            config = smoke.resolve_runtime_config(
                base_url=None,
                env_file=env_file,
                environ={},
            )

        self.assertEqual("http://127.0.0.1:4321", config.base_url)

    def test_explicit_base_url_overrides_env_file(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "BASE_URL=http://env-file:3001\n",
                encoding="utf-8",
            )
            config = smoke.resolve_runtime_config(
                base_url="https://example.test/omniflow/",
                env_file=env_file,
                environ={},
            )

        self.assertEqual("https://example.test/omniflow", config.base_url)

    def test_process_base_url_takes_precedence_over_configured_port(self):
        config = smoke.resolve_runtime_config(
            base_url=None,
            env_file=None,
            environ={
                "BASE_URL": "http://remote.example:9876/",
                "OMNIFLOW_PORT": "4321",
            },
        )

        self.assertEqual("http://remote.example:9876", config.base_url)

    def test_empty_port_uses_compose_default(self):
        config = smoke.resolve_runtime_config(
            base_url=None,
            env_file=None,
            environ={"OMNIFLOW_PORT": ""},
        )

        self.assertEqual("http://127.0.0.1:3001", config.base_url)

    def test_invalid_port_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "OMNIFLOW_PORT"):
            smoke.resolve_runtime_config(
                base_url=None,
                env_file=None,
                environ={"OMNIFLOW_PORT": "not-a-port"},
            )

    def test_non_finite_timeout_is_rejected(self):
        with self.assertRaisesRegex(smoke.argparse.ArgumentTypeError, "finite"):
            smoke._positive_timeout("nan")


class ReadSmokeTests(unittest.TestCase):
    def test_default_checks_are_read_only(self):
        opener = RecordingOpener()
        client = smoke.SmokeClient(
            "http://example.test",
            opener=opener,
        )

        with contextlib.redirect_stdout(io.StringIO()):
            smoke.run_read_checks(client)

        self.assertTrue(opener.requests)
        self.assertEqual({"GET"}, {method for method, *_ in opener.requests})
        for _method, path, headers, _timeout in opener.requests:
            self.assertNotIn("x-device-token", headers)
        self.assertFalse(
            any(urlsplit(url).path.startswith("/api/sync/") for url in opener.urls)
        )
        requested_paths = {path for _method, path, *_ in opener.requests}
        self.assertTrue(set(smoke.INTERNAL_BLOCK_ENDPOINTS) <= requested_paths)
        self.assertIn("/api/tasks/", requested_paths)

    def test_internal_route_exposure_fails_read_checks(self):
        for exposed_path in smoke.INTERNAL_BLOCK_ENDPOINTS:
            with self.subTest(path=exposed_path):
                opener = RecordingOpener()

                def exposed_internal(request, *, timeout):
                    if urlsplit(request.full_url).path == exposed_path:
                        return FakeResponse(200, {"status": "exposed"})
                    return opener(request, timeout=timeout)

                client = smoke.SmokeClient(
                    "http://example.test",
                    opener=exposed_internal,
                )
                with (
                    contextlib.redirect_stdout(io.StringIO()),
                    self.assertRaisesRegex(RuntimeError, "expected HTTP"),
                ):
                    smoke.run_read_checks(client)

    def test_public_success_response_still_requires_json(self):
        opener = RecordingOpener()

        def invalid_health(request, *, timeout):
            if urlsplit(request.full_url).path == "/healthz":
                return FakeResponse(200, b"<html>unexpected</html>")
            return opener(request, timeout=timeout)

        client = smoke.SmokeClient("http://example.test", opener=invalid_health)
        with (
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(RuntimeError, "invalid JSON"),
        ):
            smoke.run_read_checks(client)

    def test_degraded_ai_payload_fails_even_with_http_200(self):
        opener = RecordingOpener()
        opener.ai_payload = {
            "status": "degraded",
            "service": "ai",
            "database_available": True,
            "ollama_available": False,
            "index_available": True,
        }
        client = smoke.SmokeClient("http://example.test", opener=opener)

        with (
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(RuntimeError, "AI health"),
        ):
            smoke.run_read_checks(client)

    def test_api_probe_requires_a_list_payload(self):
        opener = RecordingOpener()

        def invalid_tasks(request, *, timeout):
            if urlsplit(request.full_url).path == "/api/tasks/":
                return FakeResponse(200, {"error": "not actually ready"})
            return opener(request, timeout=timeout)

        client = smoke.SmokeClient("http://example.test", opener=invalid_tasks)
        with (
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(RuntimeError, "API/database health"),
        ):
            smoke.run_read_checks(client)


class WriteSmokeTests(unittest.TestCase):
    def test_failed_update_still_attempts_task_cleanup(self):
        opener = RecordingOpener()
        opener.fail_update = True
        client = smoke.SmokeClient("http://example.test", opener=opener)
        stderr = io.StringIO()

        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(stderr),
            self.assertRaisesRegex(RuntimeError, "forced update failure"),
        ):
            smoke.run_write_check(client)

        methods_and_paths = [(method, path) for method, path, *_ in opener.requests]
        self.assertIn(("DELETE", "/api/tasks/42"), methods_and_paths)
        self.assertIn("--write creates", stderr.getvalue())

    def test_successful_write_lifecycle_always_ends_with_delete(self):
        opener = RecordingOpener()
        client = smoke.SmokeClient("http://example.test", opener=opener)

        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            smoke.run_write_check(client)

        methods_and_paths = [(method, path) for method, path, *_ in opener.requests]
        self.assertEqual(("DELETE", "/api/tasks/42"), methods_and_paths[-1])


if __name__ == "__main__":
    unittest.main()
