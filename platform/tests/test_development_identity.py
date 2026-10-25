"""Removed product modes reject configuration before creating identities or keys."""
import importlib.util
import os
import unittest
from unittest.mock import patch

from agent_factory.config import Settings


class RemovedDevelopmentIdentityTests(unittest.TestCase):
    def test_removed_product_modules_are_not_importable(self):
        self.assertIsNone(importlib.util.find_spec('agent_factory.development_identity'))

    def test_removed_settings_are_not_alternative_login_modes(self):
        for option in ('demo', 'development_mock_login', 'development_public_origin',
                       'development_profile', 'development_live_validation'):
            with self.subTest(option=option), self.assertRaises(TypeError):
                Settings(db_url='postgresql://unused', jwt_key='synthetic-signing-key-at-least-32bytes', **{option: True})

    def test_missing_key_and_obsolete_environment_fail_closed(self):
        with self.assertRaises(ValueError):
            Settings(db_url='postgresql://unused')
        for values in ({'FACTORY_MODE': 'demo'}, {'FACTORY_DEVELOPMENT_PROFILE': 'opencode-go'},
                       {'FACTORY_DATABASE_URL': 'postgresql://unused'}):
            with self.subTest(names=list(values)), patch.dict(os.environ, values, clear=True), self.assertRaises(ValueError):
                Settings.from_env()
