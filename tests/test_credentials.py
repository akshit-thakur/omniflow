import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from api.app import credentials


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'operator_password'
        env = patch.dict(os.environ, {'OPERATOR_PASSWORD_FILE': str(self.path)}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_setup_persists_hash_and_refuses_replacement(self):
        self.assertEqual('', credentials.read_credential())
        credentials.set_password('first-long-password')
        saved = self.path.read_bytes()
        self.assertNotIn(b'first-long-password', saved)
        self.assertTrue(credentials.verify('first-long-password'))
        self.assertFalse(credentials.verify('wrong'))
        with self.assertRaises(FileExistsError):
            credentials.set_password('another-long-password')
        self.assertEqual(saved, self.path.read_bytes())

    def test_legacy_password_survives_environment_changes(self):
        self.path.write_text('legacy-long-password\n')
        with patch.dict(os.environ, {'OPERATOR_PASSWORD': 'different-password'}):
            self.assertTrue(credentials.verify('legacy-long-password'))
            with self.assertRaises(FileExistsError):
                credentials.set_password('another-long-password')
        self.assertEqual('legacy-long-password\n', self.path.read_text())

    def test_explicit_recovery_changes_session_fingerprint(self):
        credentials.set_password('first-long-password')
        original = credentials.fingerprint()
        credentials.set_password('replacement-password', reset=True)
        self.assertNotEqual(original, credentials.fingerprint())
        self.assertFalse(credentials.verify('first-long-password'))
        self.assertTrue(credentials.verify('replacement-password'))

    def test_empty_existing_file_fails_closed(self):
        self.path.touch()
        with self.assertRaises(RuntimeError):
            credentials.read_credential()
        credentials.set_password('recovered-password', reset=True)
        self.assertTrue(credentials.verify('recovered-password'))

    def test_weak_password_does_not_create_file(self):
        with self.assertRaises(ValueError):
            credentials.set_password('short')
        self.assertFalse(self.path.exists())
