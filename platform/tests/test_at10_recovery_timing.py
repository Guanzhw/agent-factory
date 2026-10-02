"""Offline contracts for public, bounded recovery diagnostics."""
import asyncio
from contextlib import contextmanager
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from inference_tree_worker import RecoveryRecorder, install_recovery_timing


class RecoveryTimingTests(unittest.TestCase):
    def setUp(self):
        from agent_factory import inference_wait
        from agent_factory.control_commands import ControlCommands
        for method in ('prepare_pause', 'publish_pause', 'observe', 'validate_requirement'):
            self.enterContext(patch.object(inference_wait, method, getattr(inference_wait, method)))
        for method in ('_prepare', 'dispatch'):
            self.enterContext(patch.object(ControlCommands, method, getattr(ControlCommands, method)))
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'recovery.json'
        self.recorder = RecoveryRecorder(self.path)

    def test_denial_preserved_without_raw_detail_or_identity(self):
        for code, expected in [('APPROVED_RECOVERY_PROOF', 'APPROVED_RECOVERY_PROOF'),
                               ('INFERENCE_WAIT_EXPIRED', 'INFERENCE_WAIT_EXPIRED'),
                               ('private-value', 'HTTP_OTHER')]:
            error = HTTPException(409, code + ': private-value')
            with self.assertRaises(HTTPException) as caught:
                with self.recorder.measure('eligibility', identity={
                    'proofPresent': True, 'queueOwnerMatches': False,
                    'owner': 'private-value', 'queueRunMatches': 'private-value'}):
                    raise error
            self.assertIs(caught.exception, error)
            event = json.loads(self.path.read_text())['events'][-1]
            self.assertEqual(event['outcome'], expected)
            self.assertEqual(event['identity'], {'proofPresent': True, 'queueOwnerMatches': False})
            self.assertNotIn('private-value', self.path.read_text())

    def test_cancellation_and_fixed_bounded_events(self):
        error = asyncio.CancelledError('private-value')
        with self.assertRaises(asyncio.CancelledError) as caught:
            with self.recorder.measure('completed-launch'):
                raise error
        self.assertIs(caught.exception, error)
        self.assertEqual(json.loads(self.path.read_text())['events'][-1]['outcome'], 'CANCELLED')
        with self.assertRaises(ValueError):
            with self.recorder.measure('private-value'):
                pass
        for _ in range(260):
            with self.recorder.measure('proof'):
                pass
        self.assertEqual(len(json.loads(self.path.read_text())['events']), 256)

    def test_pause_and_command_stages_preserve_calls_and_failures(self):
        from contextlib import ExitStack
        from unittest.mock import AsyncMock, Mock
        from agent_factory import inference_wait
        from agent_factory.control_commands import ControlCommands
        from agent_factory.delegation import DelegationService
        with ExitStack() as stack:
            for method in ('approved_recovery', '_approval_payload', '_completed_launch'):
                stack.enter_context(patch.object(ControlCommands, method))
            stack.enter_context(patch.object(DelegationService, '_root_lock'))
            sync = {}
            for method in ('prepare_pause', 'publish_pause', 'observe', 'validate_requirement'):
                sync[method] = stack.enter_context(patch.object(inference_wait, method, Mock(return_value='unchanged')))
            commands = {}
            for method in ('_prepare', 'dispatch'):
                commands[method] = stack.enter_context(patch.object(ControlCommands, method, AsyncMock(return_value='unchanged')))
            install_recovery_timing(self.path)
            for method, original in sync.items():
                self.assertEqual(getattr(inference_wait, method)('private-value', marker=True), 'unchanged')
                original.assert_called_once_with('private-value', marker=True)
            for method, original in commands.items():
                self.assertEqual(asyncio.run(getattr(ControlCommands, method)('private-value', marker=True)), 'unchanged')
                original.assert_awaited_once_with('private-value', marker=True)
            error = HTTPException(409, 'INFERENCE_WAIT_EXPIRED: private-value')
            sync['observe'].side_effect = error
            with self.assertRaises(HTTPException) as caught:
                inference_wait.observe('private-value')
            self.assertIs(caught.exception, error)
        events = json.loads(self.path.read_text())['events']
        self.assertEqual([event['stage'] for event in events], ['prepare-pause', 'publish-pause',
            'observe-wait', 'validate-requirement', 'command-prepare', 'command-dispatch', 'observe-wait'])
        self.assertEqual(events[-1]['outcome'], 'INFERENCE_WAIT_EXPIRED')
        self.assertNotIn('private-value', self.path.read_text())

    def test_service_start_records_full_health_check_and_preserves_failure(self):
        from test_actual_inference_tree import Service
        service = object.__new__(Service)
        service.startup_timing = self.recorder
        with patch.object(service, '_start', return_value='healthy') as start:
            self.assertEqual(service.start(), 'healthy')
            start.assert_called_once_with()
        error = AssertionError('private-value')
        with patch.object(service, '_start', side_effect=error):
            with self.assertRaises(AssertionError) as caught:
                service.start()
            self.assertIs(caught.exception, error)
        events = json.loads(self.path.read_text())['events']
        self.assertEqual([event['stage'] for event in events], ['service-start', 'service-start'])
        self.assertEqual([event['outcome'] for event in events], ['OK', 'OTHER'])
        self.assertNotIn('private-value', self.path.read_text())

    def test_root_lock_yields_exact_connection_in_both_contexts(self):
        from agent_factory.control_commands import ControlCommands
        from agent_factory.delegation import DelegationService
        connection = object()
        released = []
        @contextmanager
        def original_lock(_self, _root):
            try:
                yield connection
            finally:
                released.append(True)
        with patch.object(ControlCommands, 'approved_recovery'), \
             patch.object(ControlCommands, '_approval_payload'), \
             patch.object(ControlCommands, '_completed_launch'), \
             patch.object(DelegationService, '_root_lock', original_lock):
            recorder = install_recovery_timing(self.path)
            for active in (False, True):
                token = recorder.active.set(active)
                try:
                    with DelegationService._root_lock(object(), 'synthetic-root') as actual:
                        self.assertIs(actual, connection)
                finally:
                    recorder.active.reset(token)
        self.assertEqual(released, [True, True])
        self.assertEqual([event['stage'] for event in json.loads(self.path.read_text())['events']],
                         ['root-lock-wait', 'root-lock-held'])

    def test_real_static_approval_payload_retains_class_and_instance_signature(self):
        from agent_factory.control_commands import ControlCommands
        from agent_factory.delegation import DelegationService
        # Real implementation must reach its domain proof rejection, not fail on
        # an injected instance argument. No database or native fixture is needed.
        original_descriptor = ControlCommands.__dict__['_approval_payload']
        original = original_descriptor.__func__
        task, snapshot = {'id': 'synthetic'}, {}
        receipt = {'body': {'binding': {}, 'decision': {}}, 'command_id': 'synthetic',
                   'fingerprint': 'synthetic', 'action': 'cancel'}
        with self.assertRaises(HTTPException) as expected:
            original(task, snapshot, receipt)
        with patch.object(ControlCommands, 'approved_recovery'), \
             patch.object(ControlCommands, '_approval_payload', original_descriptor), \
             patch.object(ControlCommands, '_completed_launch'), \
             patch.object(DelegationService, '_root_lock'):
            install_recovery_timing(self.path)
            self.assertIsInstance(ControlCommands.__dict__['_approval_payload'], staticmethod)
            instance = object.__new__(ControlCommands)
            from test_approved_recovery import fixture
            valid_task, valid_receipt, valid_snapshot = fixture()
            expected_success = original(valid_task, valid_snapshot, valid_receipt)
            for method in (ControlCommands._approval_payload, instance._approval_payload):
                self.assertEqual(method(valid_task, valid_snapshot, valid_receipt), expected_success)
            for method in (ControlCommands._approval_payload, instance._approval_payload):
                with self.assertRaises(HTTPException) as actual:
                    method(task, snapshot, receipt)
                self.assertEqual(actual.exception.detail, expected.exception.detail)
        self.assertEqual([event['outcome'] for event in json.loads(self.path.read_text())['events']],
                         ['OK', 'OK', 'APPROVED_RECOVERY_PROOF', 'APPROVED_RECOVERY_PROOF'])

    def test_scoped_root_lock_release_preserves_denial(self):
        from agent_factory.control_commands import ControlCommands
        from agent_factory.delegation import DelegationService
        entered = []
        error = PermissionError('private-value')
        @contextmanager
        def original_lock(_self, _root):
            entered.append('entered')
            try:
                yield
            finally:
                entered.append('released')
        async def original(_self, _task, _snapshot):
            def work():
                with DelegationService._root_lock(object(), 'private-value'):
                    raise error
            await asyncio.to_thread(work)
        with patch.object(ControlCommands, 'approved_recovery', original), \
             patch.object(ControlCommands, '_approval_payload'), \
             patch.object(ControlCommands, '_completed_launch'), \
             patch.object(DelegationService, '_root_lock', original_lock):
            install_recovery_timing(self.path)
            with self.assertRaises(PermissionError) as caught:
                asyncio.run(ControlCommands.approved_recovery(object(), {}, {}))
            self.assertIs(caught.exception, error)
        self.assertEqual(entered, ['entered', 'released'])
        events = json.loads(self.path.read_text())['events']
        self.assertEqual([event['stage'] for event in events], ['root-lock-wait', 'root-lock-held', 'eligibility'])
        self.assertEqual([event['outcome'] for event in events], ['OK', 'OTHER', 'OTHER'])
        self.assertNotIn('private-value', self.path.read_text())

    def test_wrapped_eligibility_propagates_context_to_thread_and_preserves_result(self):
        from agent_factory.control_commands import ControlCommands
        from agent_factory.delegation import DelegationService
        async def original(_self, _task, _snapshot, **kwargs):
            self.assertTrue(await asyncio.to_thread(recorder.active.get))
            return kwargs['sentinel']
        with patch.object(ControlCommands, 'approved_recovery', original), \
             patch.object(ControlCommands, '_approval_payload'), \
             patch.object(ControlCommands, '_completed_launch'), \
             patch.object(DelegationService, '_root_lock'):
            recorder = install_recovery_timing(self.path)
            result = asyncio.run(ControlCommands.approved_recovery(object(),
                {'run_id': 'synthetic-run', 'id': 'synthetic-task', 'owner_id': 'synthetic-owner'},
                {'queue': {'id': 'synthetic-run', 'session_id': 'synthetic-task', 'user_id': 'synthetic-owner'}},
                sentinel='unchanged'))
            self.assertEqual(result, 'unchanged')
            self.assertFalse(recorder.active.get())
        event = json.loads(self.path.read_text())['events'][-1]
        self.assertEqual(event['outcome'], 'OK')
        self.assertTrue(event['identity']['queueRunMatches'])
        self.assertNotIn('synthetic-', self.path.read_text())


if __name__ == '__main__':
    unittest.main()
