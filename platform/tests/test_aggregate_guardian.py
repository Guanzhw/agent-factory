"""Execute guardian parent control flow with synthetic OS/journal ports only."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import hashlib
import io
from pathlib import Path
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from agent_factory import process_enforcement_guardian as guardian


class AggregateGuardianTests(unittest.TestCase):
    def run_parent(self, *, drift=True, already_drifted=False, attach_failure=False):
        boot = '12345678-1234-1234-1234-123456789abc'
        child = {'pid': 71, 'group': 71, 'start': '100', 'state': 'S', 'bootId': boot}
        parent = dict(child, pid=72, group=72, start='99')
        binary = b'controlled synthetic executable; never executed'
        body = {'state': 'DISPATCHING', 'guardian': None, 'child': None, 'bootId': boot,
                'cancelRequested': False, 'aggregateConfig': {'synthetic': True},
                'aggregateLimitsDrift': already_drifted,
                'spec': {'executable': '/synthetic/program', 'argv': [], 'sha256': hashlib.sha256(binary).hexdigest()},
                'limits': {'wall_seconds': 1, 'cpu_seconds': 1, 'address_space_mb': 32, 'file_size_bytes': 1024}}
        calls = []
        store = [deepcopy(body)]
        released = [False]

        @contextmanager
        def journal(path):
            yield MagicMock()

        def read(conn):
            return deepcopy(store[0])

        def write(conn, value):
            store[0] = deepcopy(value)
            calls.append(('journal', value['state'], value.get('aggregateLimitsDrift', False)))

        def operation(path, method, *args):
            calls.append(('aggregate', method))
            if method == 'attach_before_exec':
                self.assertEqual(args, (child,))
                self.assertEqual(store[0]['child'], child)
                self.assertNotIn(('gate', b'G'), calls)
                self.assertNotIn(('reap',), calls)
                if attach_failure:
                    raise RuntimeError('synthetic attach failure')

        def finish(path):
            self.assertTrue(store[0]['aggregateLimitsDrift'])
            self.assertNotIn(('reap',), calls)
            calls.append(('aggregate', 'finish'))
            released[0] = True

        def projection(value):
            return {'state': 'RELEASED' if released[0] else 'ATTACHED',
                    'releasedProof': released[0], 'populated': not released[0],
                    'limitsReadbackVerified': False if released[0] else not drift,
                    'attached': True}

        def reap(pid, flags):
            self.assertTrue(released[0])
            calls.append(('reap',))
            return pid, 0  # Even an exit-code zero must not erase witnessed drift.

        def receipt(value, kind, code):
            self.assertEqual(value['state'], 'FAILED')
            self.assertEqual(kind, 'original-delegated-cgroup-released')
            self.assertEqual(code, 0)
            self.assertTrue(value['aggregateStopEvidence']['releasedProof'])
            self.assertFalse(value['aggregateStopEvidence']['limitsReadbackVerified'])
            calls.append(('receipt',))
            return {'synthetic': True}

        with ExitStack() as stack:
            replacements = {'_open_journal': journal, '_read': read, '_write': write,
                            'boot_id': lambda: boot, 'birth': lambda pid: deepcopy(child if pid == 71 else parent),
                            'aggregate_operation': operation, 'aggregate_finish': finish,
                            'aggregate_projection': projection, 'members': lambda group: [],
                            'stop_receipt': receipt, 'CHILD_ID': None}
            for name, replacement in replacements.items():
                stack.enter_context(patch.object(guardian, name, replacement))
            stack.enter_context(patch.object(guardian.sys, 'platform', 'linux'))
            stack.enter_context(patch.object(guardian.importlib, 'import_module', return_value=SimpleNamespace()))
            ports = {'O_NOFOLLOW': 0x20000, 'getpid': lambda: 72, 'open': MagicMock(side_effect=[10, 11]),
                     'fstat': lambda fd: SimpleNamespace(st_mode=stat.S_IFREG), 'dup': lambda fd: 12,
                     'fdopen': lambda *args: io.BytesIO(binary), 'lseek': lambda *args: 0,
                     'pipe': MagicMock(side_effect=[(20, 21), (22, 23)]), 'fork': lambda: 71,
                     'close': lambda fd: None, 'read': lambda *args: b'R',
                     'write': lambda fd, data: calls.append(('gate', data)), 'waitpid': reap,
                     'waitstatus_to_exitcode': lambda status: 0}
            for name, replacement in ports.items():
                stack.enter_context(patch.object(guardian.os, name, replacement, create=True))
            stack.enter_context(patch.object(guardian.time, 'monotonic', return_value=0))
            stack.enter_context(patch.object(guardian.time, 'sleep', side_effect=AssertionError('unexpected polling')))
            if attach_failure:
                with self.assertRaisesRegex(RuntimeError, 'synthetic attach failure'):
                    guardian.main(Path('synthetic-journal.sqlite'))
            else:
                guardian.main(Path('synthetic-journal.sqlite'))
        return store[0], calls

    def test_attach_before_gate_and_unreaped_child_then_drift_fails(self):
        body, calls = self.run_parent()
        self.assertLess(calls.index(('aggregate', 'attach_before_exec')), calls.index(('gate', b'G')))
        self.assertLess(calls.index(('aggregate', 'finish')), calls.index(('reap',)))
        self.assertLess(calls.index(('reap',)), calls.index(('receipt',)))
        self.assertEqual(body['state'], 'FAILED')
        self.assertTrue(body['aggregateLimitsDrift'])
        self.assertTrue(body['stoppedProof'])
        self.assertFalse(body['capacityHeld'])
        self.assertFalse(body['aggregateStopEvidence']['limitsReadbackVerified'])

    def test_previous_drift_remains_failed_when_controls_readback_recovers(self):
        body, calls = self.run_parent(drift=False, already_drifted=True)
        self.assertEqual(body['state'], 'FAILED')
        self.assertTrue(body['aggregateLimitsDrift'])
        self.assertIn(('aggregate', 'finish'), calls)

    def test_attach_failure_never_releases_exec_gate_or_reaps_child(self):
        body, calls = self.run_parent(attach_failure=True)
        self.assertNotIn(('gate', b'G'), calls)
        self.assertNotIn(('reap',), calls)
        self.assertNotIn(('receipt',), calls)
        self.assertEqual(body['state'], 'DISPATCHING')


if __name__ == '__main__':
    unittest.main()
