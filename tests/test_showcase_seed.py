import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "seed_showcase",
    ROOT / "docker" / "demo" / "seed_showcase.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load showcase seed module")
seed_showcase = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(seed_showcase)


class _FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def request(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return self.responses[path]


def _empty_responses():
    return {
        "/tasks/": [],
        "/medications/catalog": [],
        "/medications/plans": [],
        "/medications/logs": [],
        "/gym/exercises": [],
        "/gym/sets": [],
        "/gym/history": [],
        "/recipes/": [],
        "/inventory": [],
        "/meal-plans": [],
        "/media/": [],
    }


def _complete_responses():
    responses = _empty_responses()
    responses.update(
        {
            "/tasks/": [
                {"id": 1, "title": "Showcase Renew Passport"},
                {"id": 2, "title": "Showcase Submit Tax Return"},
                {"id": 3, "title": "Showcase Ambiguous Errand"},
                {"id": 4, "title": "Showcase Ambiguous Errand"},
                {"id": 5, "title": "Showcase Safety Note"},
            ],
            "/medications/catalog": [{"id": 6, "name": "Showcase Vitamin D3"}],
            "/medications/plans": [{"id": 7, "plan_name": "Showcase Morning D3"}],
            "/medications/logs": [{"id": 8, "plan_name": "Showcase Morning D3"}],
            "/gym/exercises": [
                {"id": 9, "name": "Showcase Goblet Squat"},
                {"id": 10, "name": "Showcase Cable Row"},
            ],
            "/gym/sets": [{"id": 11, "name": "Showcase Strength A"}],
            "/gym/history": [{"id": 12, "set_name": "Showcase Strength A"}],
            "/recipes/": [{"id": 13, "name": "Showcase Lemon Chickpea Bowl"}],
            "/inventory": [
                {"id": 14, "name": "Showcase Chickpeas"},
                {"id": 15, "name": "Showcase Olive Oil"},
                {"id": 16, "name": "Showcase Lemon"},
            ],
            "/meal-plans": [
                {"id": 17, "recipe_name": "Showcase Lemon Chickpea Bowl"}
            ],
            "/media/": [{"id": 18, "title": "Showcase The Expanse"}],
        }
    )
    return responses


class ShowcaseSeedTests(unittest.TestCase):
    def test_empty_database_is_safe_to_seed(self):
        state = seed_showcase.inspect_showcase(_FakeClient(_empty_responses()))

        self.assertEqual("empty", state["status"])

    def test_partial_fixture_is_rejected(self):
        responses = _empty_responses()
        responses["/tasks/"] = [{"id": 1, "title": "Showcase Renew Passport"}]
        client = _FakeClient(responses)

        with self.assertRaisesRegex(
            seed_showcase.ShowcaseError,
            "partial showcase fixture",
        ):
            seed_showcase.seed_showcase(client)

        self.assertTrue(all(not call[1] for call in client.calls))

    def test_complete_fixture_is_idempotently_verified(self):
        client = _FakeClient(_complete_responses())

        state = seed_showcase.seed_showcase(client)

        self.assertEqual("complete", state["status"])
        self.assertEqual(
            [3, 4],
            state["manifest"]["tasks"]["Showcase Ambiguous Errand"],
        )
        self.assertTrue(all(not call[1] for call in client.calls))


if __name__ == "__main__":
    unittest.main()
