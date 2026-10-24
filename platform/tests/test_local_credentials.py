"""Default local custody uses synthetic credentials and real files/SQLite."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select

from agent_factory.byok_model import PROVIDER_ID as MODEL_PROVIDER
from agent_factory.credential_vault import CredentialVaultError
from agent_factory.local_credentials import local_credential_vault, local_master_key
from agent_factory.personal_remote_provider import PROVIDER_ID as REMOTE_PROVIDER


class LocalCredentialTests(unittest.TestCase):
    def setUp(self):
        self.workspace = TemporaryDirectory(prefix="factory-local-vault-")
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        self.keys = self.root / "custody"
        self.database = self.root / "vault.sqlite"

    def engine(self):
        engine = create_engine("sqlite:///" + str(self.database))
        self.addCleanup(engine.dispose)
        return engine

    def test_first_key_is_complete_and_reused_across_restart(self):
        first = local_master_key(self.keys)
        self.assertEqual(len(first), 32)
        self.assertEqual((self.keys / "credential-vault.key").read_bytes(), first)
        with patch("agent_factory.local_credentials.secrets.token_bytes", side_effect=AssertionError("must reuse key")):
            self.assertEqual(local_master_key(self.keys), first)

    def test_concurrent_first_creation_publishes_one_complete_key(self):
        workers = 12
        ready = threading.Barrier(workers)

        def create():
            ready.wait(timeout=15)
            return local_master_key(self.keys)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            values = list(pool.map(lambda _: create(), range(workers)))
        self.assertEqual(len(set(values)), 1)
        self.assertEqual(len(values[0]), 32)
        self.assertEqual((self.keys / "credential-vault.key").read_bytes(), values[0])
        self.assertEqual([path.name for path in self.keys.iterdir()], ["credential-vault.key"])

    def test_invalid_existing_key_is_reported_and_preserved(self):
        self.keys.mkdir()
        path = self.keys / "credential-vault.key"
        original = b"synthetic-incomplete-key"
        path.write_bytes(original)
        with self.assertRaisesRegex(ValueError, "32 bytes"):
            local_master_key(self.keys)
        self.assertEqual(path.read_bytes(), original)

    def test_default_vault_restarts_with_ciphertext_and_owner_endpoint_binding(self):
        password = "synthetic-local-custody-password"
        username = "synthetic-local-custody-username"
        engine = self.engine()
        vault = local_credential_vault(engine, self.keys)
        destination = "http://10.23.45.67:8123"
        created = vault.create(owner="alice", provider_id=MODEL_PROVIDER, destination=destination,
                               username=username, password=password, request_id="local-create")
        scope = {"owner": "alice", "provider_id": MODEL_PROVIDER, "destination": destination,
                 "reference": created["credentialRef"], "revision": created["credentialRevision"]}
        self.assertEqual(vault.resolve(**scope).password, password)
        with engine.connect() as conn:
            rows = conn.execute(select(vault.credentials)).mappings().all()
            commands = conn.execute(select(vault.commands)).mappings().all()
        for secret in (password, username):
            self.assertNotIn(secret, repr(rows))
            self.assertNotIn(secret, repr(commands))
            self.assertNotIn(secret.encode(), self.database.read_bytes())
        key_before = (self.keys / "credential-vault.key").read_bytes()
        engine.dispose()
        restarted = local_credential_vault(self.engine(), self.keys)
        self.assertEqual((self.keys / "credential-vault.key").read_bytes(), key_before)
        self.assertEqual(restarted.resolve(**scope).password, password)
        self.assertEqual(restarted.recover(owner="alice", request_id="local-create"), created)
        self.assertEqual(restarted.list(owner="bob"), [])
        for altered in ({"owner": "bob"}, {"destination": "http://10.23.45.68:8123"},
                        {"destination": "http://10.23.45.67:8124"}, {"destination": "https://10.23.45.67:8123"}):
            self.assertFalse(restarted.authorize(**(scope | altered)))
            with self.assertRaises(CredentialVaultError):
                restarted.resolve(**(scope | altered))

    def test_default_provider_policies_accept_member_selected_http_origins(self):
        vault = local_credential_vault(self.engine(), self.keys)
        for provider in (MODEL_PROVIDER, REMOTE_PROVIDER):
            for destination in ("http://127.0.0.1:8088", "http://[::1]:8123", "https://192.168.20.30:9443"):
                created = vault.create(owner="alice", provider_id=provider, destination=destination,
                                       username="synthetic", password="synthetic-local-password")
                scope = {"owner": "alice", "provider_id": provider, "destination": destination,
                         "reference": created["credentialRef"], "revision": created["credentialRevision"]}
                self.assertTrue(vault.authorize(**scope))


if __name__ == "__main__":
    unittest.main()
