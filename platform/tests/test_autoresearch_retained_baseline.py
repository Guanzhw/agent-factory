"""Synthetic readonly boundary tests; no real database, baseline or device."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import autoresearch_retained_baseline as module
from test_research_manifest import example_manifest


class RetainedBaselineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'training-program').mkdir(mode=0o700)
        self.paths = (self.root/'config.json', self.root/'evaluation-receipt.json',
            self.root/'training-program'/'run-config.json')
        self.config = {'workspace': str(self.root)}
        self.receipt = {'syntheticOriginalReceipt': True}
        self.run_config = {'syntheticOriginalRunConfig': True}
        for path, data in zip(self.paths, (self.config, self.receipt, self.run_config)):
            path.write_text(json.dumps(data)); path.chmod(0o600)
        self.manifest = example_manifest()
        self.contract = {'comparisonManifest': self.manifest,
            'training': {'ownerId': 'alice'}, 'evaluatorExecution': {'ownerId': 'alice'}}
        self.captured = {'snapshots': {'original': 'pinned'}, 'contract': self.contract,
            'receipt': self.receipt, 'runConfig': self.run_config}
        # Parsing contract details is covered by its dedicated validator tests.
        # Here only original-files/service-lifecycle/async wiring is substituted.
        for name, replacement in (('config_from_bytes', lambda raw: json.loads(raw)),
                ('validate_evaluation_contract', lambda value: deepcopy(value))):
            p = patch.object(module, name, replacement); p.start(); self.addCleanup(p.stop)
        p = patch.object(module, 'build_baseline_snapshots', side_effect=lambda _: deepcopy(self.captured))
        self.capture = p.start(); self.addCleanup(p.stop)
        self.service = object.__new__(module.ResearchEvaluationService)
        self.opened, self.closed, self.threads = [], [], []
        @contextmanager
        def factory(captured):
            self.opened.append(captured); self.threads.append(threading.get_ident())
            try: yield self.service
            finally: self.closed.append(True)
        self.factory = factory
        self.observation = {'status': 'completed', 'valBpb': 1.5}
        p = patch.object(module, 'verify_retained_baseline', new=AsyncMock(return_value=self.observation))
        self.verify = p.start(); self.addCleanup(p.stop)
        self.reader = module.RetainedBaselineReader(*self.paths,
            expected_manifest_sha256=module.manifest_fingerprint(self.manifest), owner_id='alice', service_factory=factory)

    @unittest.skipUnless(sys.platform != 'win32', 'Private original file contract is POSIX')
    async def test_fresh_files_and_service_per_call_offloop_closed_without_writes(self):
        before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in self.paths]
        first = await self.reader(); first['valBpb'] = 99
        second = await self.reader()
        self.assertEqual(second, self.observation)
        self.assertEqual(self.capture.call_count, 2); self.assertEqual(self.verify.await_count, 2)
        self.assertEqual(len(self.closed), 2)
        self.assertTrue(all(t != threading.get_ident() for t in self.threads))
        self.assertEqual(before, [(p.read_bytes(), p.stat().st_mtime_ns) for p in self.paths])
        self.assertEqual(self.opened[0]['originalConfig'], self.config)

    @unittest.skipUnless(sys.platform != 'win32', 'Private original file contract is POSIX')
    async def test_changed_receipt_or_owner_denied_before_service_and_no_cached_acceptance(self):
        await self.reader()
        self.paths[1].write_text('{"different":true}')
        with self.assertRaises(ValueError): await self.reader()
        self.assertEqual(len(self.opened), 1); self.assertEqual(self.verify.await_count, 1)
        self.paths[1].write_text(json.dumps(self.receipt))
        self.captured['contract']['training']['ownerId'] = 'bob'
        with self.assertRaises(ValueError): await self.reader()
        self.assertEqual(len(self.opened), 1)

    @unittest.skipUnless(sys.platform != 'win32', 'Private original file contract is POSIX')
    async def test_verifier_revocation_closes_context_preserves_exception_no_retry(self):
        error = PermissionError('synthetic original authority revoked')
        self.verify.side_effect = error
        with self.assertRaises(PermissionError) as caught: await self.reader()
        self.assertIs(caught.exception, error)
        self.assertEqual(len(self.opened), 1); self.assertEqual(len(self.closed), 1)
        self.assertEqual(self.verify.await_count, 1)

    async def test_wrong_service_class_cannot_supply_trusted_boolean_or_observation(self):
        self.reader._load = Mock(return_value=self.captured)
        @contextmanager
        def wrong(_): yield {'verified': True, 'observation': self.observation}
        self.reader.service_factory = wrong
        with self.assertRaises(ValueError): await self.reader()
        self.verify.assert_not_awaited()

    async def test_async_verification_cancellation_never_opens_new_context(self):
        started, release = threading.Event(), threading.Event()
        self.reader._load = Mock(return_value=self.captured)
        async def blocked(**kwargs):
            started.set()
            await asyncio.to_thread(release.wait, 2)
            return self.observation
        self.verify.side_effect = blocked
        task = asyncio.create_task(self.reader())
        self.assertTrue(await asyncio.to_thread(started.wait, 2))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        release.set()
        for _ in range(100):
            if self.closed: break
            await asyncio.sleep(.01)
        self.assertEqual(len(self.opened), 1); self.assertEqual(len(self.closed), 1)
        self.assertEqual(self.verify.await_count, 1)
