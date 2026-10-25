import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_factory.process_enforcement import BoundedProcessAdapter, ProcessEnforcementError
from agent_factory.ssh_process_contract import PROTOCOL, MAX_REQUEST_BYTES, encoded, request, specification
from agent_factory.ssh_process_helper import handle, directory, read_file


@unittest.skipUnless(sys.platform == 'linux', 'requires Linux no-follow descriptors and flock')
class SSHProcessHelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(TemporaryDirectory())
        self.root = Path(self.temp) / 'runs'
        self.root.mkdir(mode=0o700)
        self.value = {'protocol': PROTOCOL, 'action': 'submit', 'root': str(self.root),
            'binding': {'leaseId': 'lease-1', 'operationId': 'operation-1', 'ownerId': 'alice',
                        'taskId': 'task-1', 'runId': 'run-1', 'planId': 'plan-1', 'requestId': 'request-1',
                        'planHash': 'a' * 64, 'targetFingerprint': 'b' * 64},
            'spec': {'executable': '/usr/bin/python3', 'sha256': 'c' * 64, 'argv': ['-B']},
            'limits': {'cpu_seconds': 1, 'address_space_mb': 128, 'file_size_bytes': 65536, 'wall_seconds': 3.0}}
        self.observation = {'id': 'process-1', 'ownerId': 'alice', 'taskId': 'task-1',
                            'requestId': 'request-1', 'state': 'RUNNING', 'stoppedProof': False,
                            'specSha256': hashlib.sha256(encoded({'spec': self.value['spec'],
                                'limits': self.value['limits']}, MAX_REQUEST_BYTES)).hexdigest()}

    def adapter(self):
        factory = self.enterContext(patch('agent_factory.ssh_process_helper.BoundedProcessAdapter'))
        factory.create.return_value.launch.return_value = self.observation
        factory.return_value.inspect.return_value = self.observation
        factory.return_value.cancel.return_value = self.observation
        return factory

    def test_duplicate_submit_only_reads_original_journal(self):
        factory = self.adapter()
        first = handle(self.value)
        second = handle(json.loads(json.dumps(self.value, sort_keys=True)))
        self.assertEqual(first, second)
        factory.create.assert_called_once()
        factory.create.return_value.launch.assert_called_once()
        factory.return_value.inspect.assert_called_once_with(owner_id='alice')

    def test_incomplete_prior_intent_never_recreates_or_launches(self):
        factory = self.adapter()
        (self.root / 'lease-1').mkdir(mode=0o700)
        with self.assertRaises(FileNotFoundError):
            handle(self.value)
        factory.create.assert_not_called()

    def test_inspection_and_cancellation_do_not_create(self):
        factory = self.adapter()
        for action in ('inspect', 'cancel', 'reclaim', 'output'):
            with self.subTest(action=action), self.assertRaises(FileNotFoundError):
                handle({**self.value, 'action': action})
        self.assertEqual(list(self.root.iterdir()), [])
        factory.create.assert_not_called()

    def test_changed_binding_rejected_before_remote_effect(self):
        factory = self.adapter()
        handle(self.value)
        for field in ('ownerId', 'taskId', 'operationId', 'runId'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                handle({**self.value, 'binding': {**self.value['binding'], field: 'different'}})
        self.assertEqual(factory.create.call_count, 1)
        factory.return_value.inspect.assert_not_called()

    def test_symlink_target_cannot_redirect_custody(self):
        factory = self.adapter()
        other = Path(self.temp) / 'elsewhere'
        other.mkdir(mode=0o700)
        (self.root / 'lease-1').symlink_to(other, target_is_directory=True)
        with self.assertRaises(OSError):
            handle(self.value)
        self.assertEqual(list(other.iterdir()), [])
        factory.create.assert_not_called()

    def test_output_requires_original_stop_and_rejects_symlinks(self):
        factory = self.adapter()
        handle(self.value)
        with self.assertRaises(ValueError):
            handle({**self.value, 'action': 'output'})
        factory.return_value.inspect.return_value = {**self.observation, 'state': 'FAILED', 'stoppedProof': True}
        output = self.root / 'lease-1' / 'custody.output'
        output.write_bytes(b'negative-result\n')
        receipt = handle({**self.value, 'action': 'output'})['output']
        self.assertEqual(receipt['sha256'], hashlib.sha256(b'negative-result\n').hexdigest())
        output.unlink()
        output.symlink_to(Path(self.temp) / 'private')
        with self.assertRaises(OSError):
            handle({**self.value, 'action': 'output'})

    def test_replaced_journal_spec_is_not_original_execution(self):
        factory = self.adapter()
        handle(self.value)
        factory.return_value.inspect.return_value = {**self.observation, 'specSha256': 'd' * 64}
        with self.assertRaises(ValueError):
            handle({**self.value, 'action': 'inspect'})

    def test_foreign_same_owner_journal_is_unchanged_by_cancel(self):
        for field in ('task', 'request', 'spec'):
            with self.subTest(field=field), TemporaryDirectory(dir=self.root) as folder:
                run = Path(folder)
                value = {**self.value, 'binding': {**self.value['binding'], 'leaseId': run.name}}
                descriptor = {key: request(value)[key] for key in ('protocol', 'binding', 'root', 'spec', 'limits')}
                (run / 'binding.json').write_bytes(encoded(descriptor, MAX_REQUEST_BYTES))
                spec, limits = specification({**value['spec'], 'argv': ['-S']}
                    if field == 'spec' else value['spec'], value['limits'])
                journal = run / 'custody.sqlite'
                BoundedProcessAdapter.create(journal, owner_id='alice',
                    task_id='foreign-task' if field == 'task' else 'task-1',
                    request_id='foreign-request' if field == 'request' else 'request-1', spec=spec, limits=limits)
                before = journal.read_bytes()
                with patch.object(BoundedProcessAdapter, 'cancel', wraps=BoundedProcessAdapter(journal).cancel) as cancel:
                    with self.assertRaises(ValueError):
                        handle({**value, 'action': 'cancel'})
                    cancel.assert_not_called()
                self.assertEqual(journal.read_bytes(), before)

    def test_protocol_rejects_extra_fields_and_path_escape(self):
        for value in ({**self.value, 'shell': 'anything'},
                      {**self.value, 'root': self.temp + '/../escape'},
                      {**self.value, 'binding': {**self.value['binding'], 'leaseId': '..'}},
                      {**self.value, 'limits': {**self.value['limits'], 'gpu': 1}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                request(value)

    def test_capability_query_is_read_only_and_not_gpu_allocation(self):
        result = handle({'protocol': PROTOCOL, 'action': 'capabilities', 'root': str(self.root)})
        self.assertFalse(result['gpuAllocation'])
        self.assertFalse(result['scheduler'])
        self.assertFalse(result['automaticInstallation'])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_capability_root_checks_are_read_only_and_reject_missing_or_unsafe_directory(self):
        missing = self.root / 'missing'
        with self.assertRaises(FileNotFoundError):
            handle({'protocol': PROTOCOL, 'action': 'capabilities', 'root': str(missing)})
        self.assertFalse(missing.exists())
        self.root.chmod(0o755)
        with self.assertRaises(ValueError):
            handle({'protocol': PROTOCOL, 'action': 'capabilities', 'root': str(self.root)})
        self.assertEqual(list(self.root.iterdir()), [])


class SSHProcessUnsupportedPlatformTests(unittest.TestCase):
    def test_os_entrypoints_reject_before_parsing_or_file_access(self):
        for platform in ('win32', 'darwin'):
            with self.subTest(platform=platform), patch('agent_factory.ssh_process_helper.sys.platform', platform), \
                    patch('agent_factory.ssh_process_helper.os.open') as opened, \
                    patch('agent_factory.ssh_process_helper.request') as parsed:
                with self.assertRaisesRegex(ProcessEnforcementError, 'SSH_PROCESS_PLATFORM_UNSUPPORTED'):
                    handle(None)
                with self.assertRaisesRegex(ProcessEnforcementError, 'SSH_PROCESS_PLATFORM_UNSUPPORTED'):
                    with directory('/unsupported'):
                        self.fail('unsupported directory was entered')
                with self.assertRaisesRegex(ProcessEnforcementError, 'SSH_PROCESS_PLATFORM_UNSUPPORTED'):
                    read_file(-1, 'unsupported', 1)
                opened.assert_not_called()
                parsed.assert_not_called()
