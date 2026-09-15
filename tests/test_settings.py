import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ai.app import settings as ai_settings
from api.app import settings as api_settings


class FileBackedSecretTests(unittest.TestCase):
    def _modules(self):
        return (api_settings, ai_settings)

    def test_secret_file_is_used_when_direct_value_is_absent(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            path.write_text("generated-secret\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                os.environ["TEST_SECRET_FILE"] = str(path)
                for module in self._modules():
                    self.assertEqual(
                        "generated-secret",
                        module._secret_value(
                            "TEST_SECRET",
                            "TEST_SECRET_FILE",
                            "fallback",
                        ),
                    )

    def test_direct_and_file_values_are_rejected_together(self):
        with patch.dict(
            os.environ,
            {
                "TEST_SECRET": "direct-secret",
                "TEST_SECRET_FILE": "/does/not/exist",
            },
            clear=True,
        ):
            for module in self._modules():
                with self.assertRaisesRegex(RuntimeError, "both"):
                    module._secret_value("TEST_SECRET", "TEST_SECRET_FILE", "fallback")

    def test_secret_file_preserves_intentional_whitespace(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            path.write_text("  spaced secret  \r\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"TEST_SECRET_FILE": str(path)},
                clear=True,
            ):
                for module in self._modules():
                    self.assertEqual(
                        "  spaced secret  ",
                        module._secret_value(
                            "TEST_SECRET",
                            "TEST_SECRET_FILE",
                            "fallback",
                        ),
                    )

    def test_multiline_secret_file_fails_closed(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            path.write_text("first\nsecond\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"TEST_SECRET_FILE": str(path)},
                clear=True,
            ):
                for module in self._modules():
                    with self.assertRaisesRegex(RuntimeError, "exactly one line"):
                        module._secret_value(
                            "TEST_SECRET",
                            "TEST_SECRET_FILE",
                            "fallback",
                        )

    def test_missing_or_empty_configured_file_fails_closed(self):
        with TemporaryDirectory() as directory:
            empty_path = Path(directory) / "empty"
            empty_path.write_text("\n", encoding="utf-8")
            for path, message in (
                (Path(directory) / "missing", "Unable to read TEST_SECRET_FILE"),
                (empty_path, "empty or whitespace-only"),
            ):
                with patch.dict(
                    os.environ,
                    {"TEST_SECRET_FILE": str(path)},
                    clear=True,
                ):
                    for module in self._modules():
                        with self.assertRaisesRegex(RuntimeError, message):
                            module._secret_value(
                                "TEST_SECRET",
                                "TEST_SECRET_FILE",
                                "fallback",
                            )


class SettingsValidationTests(unittest.TestCase):
    credentials = {
        "DATABASE_PASSWORD": "test-db-password-123456789",
        "AI_SERVICE_SECRET": "test-service-secret-123456789012345678901234567890",
        "OPERATOR_PASSWORD": "test-operator-password-123456",
    }
    def tearDown(self):
        api_settings.get_settings.cache_clear()
        ai_settings.get_settings.cache_clear()

    def test_api_rejects_an_inverted_pool_range(self):
        with patch.dict(
            os.environ,
            {"DB_POOL_MIN_SIZE": "9", "DB_POOL_MAX_SIZE": "2"},
            clear=True,
        ):
            api_settings.get_settings.cache_clear()
            with self.assertRaisesRegex(RuntimeError, "cannot exceed"):
                api_settings.get_settings()

    def test_api_rejects_a_non_finite_command_timeout(self):
        with patch.dict(
            os.environ,
            {**self.credentials, "DB_COMMAND_TIMEOUT": "nan"},
            clear=True,
        ):
            api_settings.get_settings.cache_clear()
            with self.assertRaisesRegex(RuntimeError, "finite"):
                api_settings.get_settings()

    def test_ai_rejects_invalid_boolean_text(self):
        with patch.dict(os.environ, {**self.credentials, "AUTO_REINDEX": "sometimes"}, clear=True):
            ai_settings.get_settings.cache_clear()
            with self.assertRaisesRegex(RuntimeError, "AUTO_REINDEX"):
                ai_settings.get_settings()

    def test_ai_rejects_an_incompatible_embedding_model(self):
        for model in ("all-minilm", "bge-m3:"):
            with self.subTest(model=model), patch.dict(
                os.environ,
                {**self.credentials, "OLLAMA_EMBED_MODEL": model},
                clear=True,
            ):
                ai_settings.get_settings.cache_clear()
                with self.assertRaisesRegex(RuntimeError, "1024-dimensional"):
                    ai_settings.get_settings()

    def test_ai_rejects_invalid_semantic_distance(self):
        for value in ("nan", "0", "2.1", "not-a-number"):
            with self.subTest(value=value), patch.dict(
                os.environ,
                {**self.credentials, "MAX_SEMANTIC_DISTANCE": value},
                clear=True,
            ):
                ai_settings.get_settings.cache_clear()
                with self.assertRaisesRegex(RuntimeError, "MAX_SEMANTIC_DISTANCE"):
                    ai_settings.get_settings()


if __name__ == "__main__":
    unittest.main()
