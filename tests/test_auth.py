import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from tempfile import TemporaryDirectory

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from app.main import app  # noqa: E402
from app import settings  # noqa: E402


class OperatorBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.environment = {
            "DATABASE_PASSWORD": "test-db-password-123456789",
            "AI_SERVICE_SECRET": "test-service-secret-123456789012345678901234567890",
            "OPERATOR_PASSWORD": "test-operator-password-123456",
        }
        self.environment_patch = patch.dict(os.environ, self.environment, clear=False)
        self.environment_patch.start()
        settings.get_settings.cache_clear()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        settings.get_settings.cache_clear()
        self.environment_patch.stop()

    async def test_sensitive_read_requires_operator_session(self):
        response = await self.client.get("/api/tasks/")
        self.assertEqual(401, response.status_code)

    async def test_first_run_setup_is_once_only_and_reset_revokes_session(self):
        from app.credentials import set_password
        with TemporaryDirectory() as directory, patch.dict(os.environ, {
            "OPERATOR_PASSWORD": "", "OPERATOR_PASSWORD_FILE": str(Path(directory) / 'operator_password'),
        }):
            self.assertTrue((await self.client.get('/api/auth/status')).json()['setup_required'])
            rejected = await self.client.post('/api/auth/setup', json={'password': 'first-long-password'}, headers={'Origin': 'http://foreign.invalid'})
            self.assertEqual(403, rejected.status_code)
            result = await self.client.post('/api/auth/setup', json={'password': 'first-long-password'}, headers={'Origin': 'http://testserver'})
            self.assertEqual(200, result.status_code)
            token = result.json()['access_token']
            duplicate = await self.client.post('/api/auth/setup', json={'password': 'different-password'}, headers={'Origin': 'http://testserver'})
            self.assertEqual(409, duplicate.status_code)
            headers = {'Authorization': f'Bearer {token}'}
            self.assertEqual(200, (await self.client.get('/api/auth/session', headers=headers)).status_code)
            set_password('replacement-password', reset=True)
            self.assertEqual(401, (await self.client.get('/api/auth/session', headers=headers)).status_code)

    async def test_demo_skips_password_but_rejects_foreign_origin(self):
        with patch.dict(os.environ, {'OMNIFLOW_DEMO': 'true'}):
            self.assertTrue((await self.client.get('/api/auth/status')).json()['demo'])
            self.assertEqual(200, (await self.client.get('/api/auth/session')).status_code)
            response = await self.client.post('/api/tasks/', json={'title': 'foreign'}, headers={'Origin': 'http://foreign.invalid'})
            self.assertEqual(403, response.status_code)

    async def test_wrong_credential_and_foreign_origin_cannot_mutate(self):
        wrong = await self.client.post("/api/auth/login", json={"password": "wrong"})
        self.assertEqual(401, wrong.status_code)
        login = await self.client.post(
            "/api/auth/login", json={"password": self.environment["OPERATOR_PASSWORD"]}
        )
        self.assertEqual(200, login.status_code)
        credentials = login.json()
        response = await self.client.post(
            "/api/ai/proposals/00000000-0000-0000-0000-000000000000/approve",
            headers={"Authorization": f"Bearer {credentials['access_token']}", "Origin": "http://attacker.invalid", "X-CSRF-Token": credentials["csrf_token"]},
        )
        self.assertEqual(403, response.status_code)
