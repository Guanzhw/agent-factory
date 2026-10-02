"""Version-proof caching retains fresh permissions and full binary hash checks."""
import asyncio
from dataclasses import replace
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from agent_factory.openresearch import (
    BinaryPin, CommandResult, OpenResearchAdapter, OpenResearchError, REVISION, VERSION,
)


class OrxVersionProofTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.binary = root / "synthetic-orx"
        self.binary.write_bytes(b"Synthetic fixture; never executable")
        self.authorize = Mock(return_value=True)
        self.adapter = OpenResearchAdapter(binary=self.binary, scope=root / "scope",
            owner_id="synthetic-owner", task_id=str(uuid4()), authorize=self.authorize,
            pin=self.pin(), enabled=True)
        self.execute = AsyncMock(return_value=self.result(f"orx {VERSION}"))
        self.adapter._execute = self.execute

    def pin(self):
        return BinaryPin(REVISION, VERSION, hashlib.sha256(self.binary.read_bytes()).hexdigest())

    def result(self, stdout):
        return CommandResult(("--no-telemetry", "--version"), stdout, "", 0, 0,
                             hashlib.sha256(stdout.encode()).hexdigest())

    async def test_repeat_preflight_reuses_only_version_proof(self):
        self.assertIsNone(self.adapter._version_proof)
        with patch.object(self.adapter, "_verify_hash", wraps=self.adapter._verify_hash) as verify:
            first = await self.adapter.preflight()
            second = await self.adapter.preflight()
        self.assertEqual(first, second)
        self.assertEqual(self.authorize.call_args_list, [(('preflight',),), (('preflight',),)])
        self.assertEqual(verify.call_count, 2)
        self.execute.assert_awaited_once_with(("--no-telemetry", "--version"))
        self.assertEqual(self.adapter._version_proof, self.adapter.pin)

    async def test_new_exact_pin_requires_new_version_proof(self):
        await self.adapter.preflight()
        old_pin = self.adapter.pin
        self.binary.write_bytes(b"Second synthetic build; also never executable")
        self.adapter.pin = self.pin()
        self.assertNotEqual(self.adapter.pin, old_pin)
        await self.adapter.preflight()
        await self.adapter.preflight()
        self.assertEqual(self.execute.await_count, 2)
        self.assertEqual(self.adapter._version_proof, self.adapter.pin)

    async def test_cached_version_does_not_allow_modified_or_missing_binary(self):
        await self.adapter.preflight()
        self.binary.write_bytes(b"Synthetic unapproved replacement")
        with self.assertRaises(OpenResearchError) as caught:
            await self.adapter.preflight()
        self.assertEqual(caught.exception.code, "UNVERIFIED_BINARY")
        self.binary.unlink()
        with self.assertRaises(OpenResearchError) as missing:
            await self.adapter.preflight()
        self.assertEqual(missing.exception.code, "UNVERIFIED_BINARY")
        self.assertEqual(self.execute.await_count, 1)
        self.assertEqual(self.authorize.call_count, 3)

    async def test_cached_version_does_not_allow_changed_pin_or_disabled_adapter(self):
        await self.adapter.preflight()
        original = self.adapter.pin
        assert original is not None
        for invalid in (replace(original, revision="unapproved"), replace(original, version="0.0.0"),
                        replace(original, sha256="0" * 64), None):
            self.adapter.pin = invalid
            with self.subTest(pin=invalid), self.assertRaises(OpenResearchError) as caught:
                await self.adapter.preflight()
            self.assertEqual(caught.exception.code, "UNVERIFIED_BINARY")
        self.adapter.pin = original
        self.adapter.enabled = False
        with self.assertRaises(OpenResearchError) as disabled:
            await self.adapter.preflight()
        self.assertEqual(disabled.exception.code, "DISABLED")
        self.assertEqual(self.execute.await_count, 1)

    async def test_cached_version_never_bypasses_revocation(self):
        await self.adapter.preflight()
        self.authorize.return_value = False
        with self.assertRaises(OpenResearchError) as caught:
            await self.adapter.preflight()
        self.assertEqual(caught.exception.code, "FORBIDDEN")
        self.assertEqual(self.execute.await_count, 1)
        self.assertEqual(self.authorize.call_count, 2)

    async def test_mismatched_or_failed_version_is_never_cached(self):
        self.execute.return_value = self.result("orx 0.0.0")
        for _ in range(2):
            with self.assertRaises(OpenResearchError) as caught:
                await self.adapter.preflight()
            self.assertEqual(caught.exception.code, "VERSION_MISMATCH")
            self.assertIsNone(self.adapter._version_proof)
        self.assertEqual(self.execute.await_count, 2)
        self.execute.side_effect = OpenResearchError("CLI_FAILED", "Synthetic failure")
        with self.assertRaises(OpenResearchError):
            await self.adapter.preflight()
        self.assertIsNone(self.adapter._version_proof)
        self.execute.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.adapter.preflight()
        self.assertIsNone(self.adapter._version_proof)
        self.execute.side_effect = None
        self.execute.return_value = self.result(f"orx {VERSION}")
        await self.adapter.preflight()
        self.assertEqual(self.adapter._version_proof, self.adapter.pin)
        self.assertEqual(self.execute.await_count, 5)

    async def test_pin_drift_during_version_command_cannot_certify_new_build(self):
        async def change_pin(*args, **kwargs):
            self.binary.write_bytes(b"Synthetic build replaced during version command")
            self.adapter.pin = self.pin()
            return self.result(f"orx {VERSION}")

        self.execute.side_effect = change_pin
        with self.assertRaises(OpenResearchError):
            await self.adapter.preflight()
        self.assertIsNone(self.adapter._version_proof)
        self.execute.side_effect = None
        await self.adapter.preflight()
        self.assertEqual(self.execute.await_count, 2)
        self.assertEqual(self.adapter._version_proof, self.adapter.pin)
