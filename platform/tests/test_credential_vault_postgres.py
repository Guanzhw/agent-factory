"""Real disposable-loopback PostgreSQL; exclusively synthetic ciphertext/keys."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
import unittest

from sqlalchemy import create_engine, select

from agent_factory.credential_vault import CredentialVaultError, EncryptedCredentialVault
from agent_factory.personal_remote_provider import PROVIDER_ID, origin
from pg_fixture import IsolatedPostgres


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
class CredentialVaultPostgresTests(unittest.TestCase):
    def test_retired_provider_owner_revoke_erases_ciphertext_without_new_authority(self):
        with IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]) as database:
            engine = create_engine(database.url)
            try:
                vault = EncryptedCredentialVault(engine, b"s" * 32, {PROVIDER_ID: origin})
                created = vault.create(owner="alice", provider_id=PROVIDER_ID, destination="https://runtime.example.com",
                    username="synthetic-user", password="synthetic-password", request_id="retire-create")
                retired = EncryptedCredentialVault(engine, b"s" * 32, {"other-installed-provider": origin})
                scope = dict(owner="alice", reference=created["credentialRef"], revision=created["credentialRevision"],
                    provider_id=PROVIDER_ID, destination=created["destination"])
                self.assertFalse(retired.authorize(**scope))
                with self.assertRaises(CredentialVaultError):
                    retired.resolve(**scope)
                command = {key: scope[key] for key in ("owner", "reference", "revision")}
                with self.assertRaises(CredentialVaultError):
                    retired.revoke(**(command | {"owner": "bob"}), request_id="retire-bob")
                receipt = retired.revoke(**command, request_id="retire-alice")
                self.assertEqual(receipt["status"], "revoked")
                self.assertEqual(retired.recover(owner="alice", request_id="retire-alice"), receipt)
                self.assertIsNone(retired.recover(owner="bob", request_id="retire-alice"))
                with engine.connect() as conn:
                    row = conn.execute(select(vault.credentials)).mappings().one()
                self.assertEqual((row["ciphertext"], row["nonce"]), (b"", b""))
            finally:
                engine.dispose()

    def test_ciphertext_restart_rotation_revoke_and_cas(self):
        database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        engine = create_engine(database.url)
        self.addCleanup(engine.dispose)
        vault = EncryptedCredentialVault(engine, b"s" * 32, {PROVIDER_ID: origin})
        value = vault.create(owner="alice", provider_id=PROVIDER_ID, destination="https://runtime.example.com",
                             username="synthetic-user", password="synthetic-password", request_id="pg-create")
        scope = dict(owner="alice", reference=value["credentialRef"], revision=value["credentialRevision"],
                     provider_id=PROVIDER_ID, destination="https://runtime.example.com")
        with engine.connect() as conn:
            row = conn.execute(select(vault.credentials)).mappings().one()
        self.assertNotIn("synthetic-password", repr(row))
        self.assertNotIn("synthetic-user", repr(row))
        restarted = EncryptedCredentialVault(engine, b"s" * 32, {PROVIDER_ID: origin})
        self.assertEqual(restarted.resolve(**scope).password, "synthetic-password")
        self.assertEqual(restarted.recover(owner="alice", request_id="pg-create"), value)
        self.assertIsNone(restarted.recover(owner="bob", request_id="pg-create"))
        self.assertEqual(restarted.create(owner="alice", provider_id=PROVIDER_ID,
            destination="https://runtime.example.com", username="synthetic-user", password="synthetic-password",
            request_id="pg-create"), value)
        with self.assertRaises(CredentialVaultError):
            restarted.create(owner="alice", provider_id=PROVIDER_ID, destination="https://runtime.example.com",
                username="synthetic-user", password="synthetic-different", request_id="pg-create")
        start = Barrier(2)
        def duplicate_create():
            start.wait(timeout=10)
            return vault.create(owner="alice", provider_id=PROVIDER_ID, destination="https://runtime.example.com",
                username="synthetic-user", password="synthetic-concurrent", request_id="pg-concurrent-create")
        with ThreadPoolExecutor(max_workers=2) as workers:
            duplicates = list(workers.map(lambda _: duplicate_create(), range(2)))
        self.assertEqual(duplicates[0], duplicates[1])
        self.assertEqual(len(vault.list(owner="alice")), 2)
        self.assertFalse(restarted.authorize(**(scope | {"owner": "bob"})))
        command = {key: scope[key] for key in ("owner", "reference", "revision")}
        # Both read the same revision before encrypting; exactly one CAS wins.
        barrier = Barrier(2)
        original_encrypt = vault._encrypt
        def synchronized_encrypt(*args):
            barrier.wait(timeout=10)
            return original_encrypt(*args)
        def rotate():
            try:
                return vault.rotate(**command, username="synthetic-user", password="synthetic-rotated")
            except CredentialVaultError:
                return None
        with patch.object(vault, "_encrypt", side_effect=synchronized_encrypt):
            with ThreadPoolExecutor(max_workers=2) as workers:
                results = list(workers.map(lambda _: rotate(), range(2)))
        winners = [result for result in results if result is not None]
        self.assertEqual(len(winners), 1)
        rotated = winners[0]
        self.assertFalse(restarted.authorize(**scope))
        with self.assertRaises(CredentialVaultError):
            restarted.rotate(**command, username="synthetic-user", password="synthetic-racing")
        scope["revision"] = rotated["credentialRevision"]
        self.assertEqual(restarted.resolve(**scope).password, "synthetic-rotated")
        restarted.revoke(**{key: scope[key] for key in ("owner", "reference", "revision")})
        self.assertFalse(vault.authorize(**scope))
        with self.assertRaises(CredentialVaultError): vault.resolve(**scope)
