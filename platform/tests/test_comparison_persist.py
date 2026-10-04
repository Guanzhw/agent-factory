# pyright: reportMissingImports=false
"""Cancellation fences for report threads, without a database or processes."""
import asyncio
import json
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from agent_factory.comparison_fixture import fixture_candidate, fixture_contract
from agent_factory.comparison_workflow import ComparisonService
from test_comparison_fixture import record


class ComparisonPersistTests(unittest.TestCase):
    def exercise(self, blocked_at):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        state = {'databaseCancelled': False, 'effect': None, 'artifacts': []}
        raw = json.dumps(record('linear-v1')).encode()
        contract = fixture_contract('a' * 64, [{'id': 'input', 'version': 1, 'sha256': 'b' * 64}])
        candidate = fixture_candidate(contract, 'linear-v1')
        task = {'id': 'task', 'owner_id': 'alice', 'run_id': 'run'}
        plan = {'id': 'plan', 'fingerprint': 'a' * 64}
        context = SimpleNamespace(user_id='alice', session_id='task', run_id='run')
        lease = {'id': 'lease', 'state': 'RECLAIMED', 'executionStatus': 'COMPLETED',
                 'exitCode': 0, 'stopEvidence': {'allStopped': True}, 'capacityHeld': False}

        def barrier():
            entered.set()
            if not release.wait(5):
                raise AssertionError('Test did not release the worker')

        def read(*_args):
            if blocked_at == 'read':
                barrier()
            return raw

        def authorize(*_args):
            # Deliberately no durable cancellation: only caller cancellation can fence writes.
            self.assertFalse(state['databaseCancelled'])

        def reserve(*_args):
            state['effect'] = 'UNKNOWN'
            return {'status': 'new'}

        def artifact(_run, name, _content, **_kwargs):
            state['artifacts'].append(name)
            if blocked_at == name:
                barrier()  # Already committed artifact; cancellation cannot undo it.
            return {'id': name, 'sha256': 'c' * 64}

        def complete(*_args):
            state['effect'] = 'DONE'

        store = SimpleNamespace(authorize_tool=Mock(side_effect=authorize),
            effect_reserve=Mock(side_effect=reserve), artifact_write=Mock(side_effect=artifact),
            effect_complete=Mock(side_effect=complete))
        service = ComparisonService(store, None)
        original = service._persist

        def tracked(*args):
            try:
                return original(*args)
            finally:
                finished.set()

        async def scenario():
            pending = asyncio.create_task(service.persist(context,
                {'leaseId': 'lease', 'nativeRunId': 'run', 'state': 'RECLAIMED'}))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                pending.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await pending
            finally:
                release.set()
                self.assertTrue(await asyncio.to_thread(finished.wait, 5))

        with patch.object(service, '_scope', return_value=(task, plan, 'linear-v1', 'target', contract, candidate)), \
             patch.object(service, '_process', return_value=(lease, SimpleNamespace(provider=SimpleNamespace(read_completed_output=read)))), \
             patch.object(service, '_persist', side_effect=tracked):
            asyncio.run(scenario())
        self.assertFalse(state['databaseCancelled'])
        store.effect_complete.assert_not_called()
        return store, state

    def test_cancel_during_output_read_prevents_all_effect_and_artifact_writes(self):
        store, state = self.exercise('read')
        store.effect_reserve.assert_not_called()
        store.artifact_write.assert_not_called()
        self.assertIsNone(state['effect'])

    def test_cancel_during_each_artifact_retains_unknown_without_done(self):
        for name, count in (('comparison-output.json', 1), ('comparison-report.json', 2)):
            with self.subTest(artifact=name):
                store, state = self.exercise(name)
                store.effect_reserve.assert_called_once()
                self.assertEqual(state['effect'], 'UNKNOWN')
                self.assertEqual(store.artifact_write.call_count, count)
                self.assertEqual(len(state['artifacts']), count)
