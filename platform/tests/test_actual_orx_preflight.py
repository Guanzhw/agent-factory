"""Opt-in actual ORX binary startup checks; no research/provider operations."""
import asyncio
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from uuid import uuid4

from agent_factory.openresearch import BinaryPin, OpenResearchAdapter, OpenResearchError


@unittest.skipUnless(os.getenv("FACTORY_ORX_BINARY") and os.getenv("FACTORY_ORX_SHA256"),
                     "Requires explicitly supplied exact-source ORX binary and digest")
class ActualOpenResearchPreflight(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = Path(os.environ["FACTORY_ORX_BINARY"]).resolve()
        cls.sha = os.environ["FACTORY_ORX_SHA256"].lower()
        if hashlib.sha256(cls.binary.read_bytes()).hexdigest() != cls.sha:
            raise AssertionError("Binary differs from explicitly supplied pin")

    def adapter(self, scope, sha=None):
        paths = [str(Path(sys.executable).parent)]
        if os.getenv("SystemRoot"):
            paths.append(os.environ["SystemRoot"])
        return OpenResearchAdapter(binary=self.binary, scope=Path(scope).resolve(),
            owner_id="synthetic-acceptance", task_id=str(uuid4()),
            authorize=lambda _operation: True, enabled=True,
            pin=BinaryPin(revision="f336b121525d99364e2dee4fe90b2784894a54e6",
                          version="0.2.13", sha256=sha or self.sha),
            search_path=os.pathsep.join(paths), command_timeout=10)

    def test_pinned_binary_actual_adapter_version(self):
        with tempfile.TemporaryDirectory(prefix="orx-version-acceptance-") as scope:
            result = asyncio.run(self.adapter(Path(scope)/"task").preflight())
        self.assertEqual(result["version"], "0.2.13")
        self.assertEqual(result["binary_sha256"], self.sha)
        self.assertEqual(result["revision"], "f336b121525d99364e2dee4fe90b2784894a54e6")

    def test_wrong_pin_rejects_before_spawn(self):
        with tempfile.TemporaryDirectory(prefix="orx-pin-rejection-") as scope:
            adapter = self.adapter(Path(scope)/"task", "0"*64)
            with mock.patch("asyncio.create_subprocess_exec", side_effect=AssertionError("Must not spawn")) as spawn:
                with self.assertRaisesRegex(OpenResearchError, "hash differs"):
                    asyncio.run(adapter.preflight())
                spawn.assert_not_called()
