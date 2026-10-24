"""Original guardian handle ownership, independent of PostgreSQL and providers."""
from pathlib import Path
import json
import subprocess
import sys
import textwrap
import threading
import time
import unittest
from unittest.mock import Mock, patch
import weakref

from agent_factory.process_enforcement import BoundedProcessAdapter, _start_guardian
import test_process_enforcement as fixture


class GuardianReaperTests(unittest.TestCase):
    def test_waiter_owns_only_original_process_and_exits_after_wait(self):
        entered, release = threading.Event(), threading.Event()
        process = Mock()
        def wait():
            entered.set()
            self.assertTrue(release.wait(2))
        process.wait.side_effect = wait
        threads = []
        original_thread = threading.Thread
        def thread(**kwargs):
            result = original_thread(**kwargs)
            threads.append(result)
            return result
        try:
            with patch('agent_factory.process_enforcement.threading.Thread', side_effect=thread), \
                    patch('agent_factory.process_enforcement.subprocess.Popen', return_value=process) as spawn:
                self.assertIs(_start_guardian(Path('/owned/custody.sqlite')), process)
            self.assertTrue(entered.wait(2))
            self.assertTrue(threads[0].daemon)
            self.assertTrue(spawn.call_args.kwargs['start_new_session'])
            process.terminate.assert_not_called()
            process.kill.assert_not_called()
        finally:
            release.set()
            for worker in threads:
                worker.join(2)
                self.assertFalse(worker.is_alive())
        process.wait.assert_called_once_with()

    def test_failed_spawn_releases_waiter(self):
        threads = []
        original_thread = threading.Thread
        def thread(**kwargs):
            result = original_thread(**kwargs)
            threads.append(result)
            return result
        with patch('agent_factory.process_enforcement.threading.Thread', side_effect=thread), \
                patch('agent_factory.process_enforcement.subprocess.Popen', side_effect=OSError('fixture')):
            with self.assertRaises(OSError):
                _start_guardian(Path('/owned/custody.sqlite'))
        threads[0].join(2)
        self.assertFalse(threads[0].is_alive())

    def test_failed_waiter_start_never_spawns(self):
        with patch('agent_factory.process_enforcement.threading.Thread') as thread, \
                patch('agent_factory.process_enforcement.subprocess.Popen') as spawn:
            thread.return_value.start.side_effect = RuntimeError('fixture thread limit')
            with self.assertRaises(RuntimeError):
                _start_guardian(Path('/owned/custody.sqlite'))
            spawn.assert_not_called()

    def test_interrupted_started_waiter_is_released_without_spawning(self):
        threads = []
        original_thread = threading.Thread
        def thread(**kwargs):
            result = original_thread(**kwargs)
            threads.append(result)
            start = result.start
            def interrupted_start():
                start()
                raise KeyboardInterrupt('fixture after actual thread start')
            result.start = interrupted_start
            return result
        with patch('agent_factory.process_enforcement.threading.Thread', side_effect=thread), \
                patch('agent_factory.process_enforcement.subprocess.Popen') as spawn:
            with self.assertRaises(KeyboardInterrupt):
                _start_guardian(Path('/owned/custody.sqlite'))
            spawn.assert_not_called()
        threads[0].join(2)
        self.assertFalse(threads[0].is_alive())


@unittest.skipUnless(sys.platform == 'linux', 'Linux guardian required')
class GuardianReaperProcessTests(unittest.TestCase):
    setUp = fixture.ProcessEnforcementTests.setUp
    adapter = fixture.ProcessEnforcementTests.adapter

    def check_reaping(self, code, expected, *, cancel=False, wall_seconds=2):
        adapter = self.adapter(code, wall_seconds=wall_seconds)
        adapter.launch(owner_id='alice', before_effect=lambda: None)
        process = adapter._process
        assert process is not None
        original = weakref.ref(adapter)
        del adapter
        self.assertIsNone(original())
        reopened = BoundedProcessAdapter(self.path)
        if cancel:
            reopened.cancel(owner_id='alice')
        result = reopened.wait(owner_id='alice')
        self.assertTrue(result['stoppedProof'])
        self.assertEqual(result['state'], expected)
        # Do not poll/wait this handle here: only the product reaper may collect
        # its exit status, independently of the reopened custody adapter.
        deadline = time.monotonic() + 2
        while process.returncode is None and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(process.returncode, 0)

    def test_reopened_custody_does_not_need_original_adapter_to_reap(self):
        self.check_reaping('import time;time.sleep(.1)', 'COMPLETED')

    def test_reopened_cancellation_reaps_original_guardian(self):
        self.check_reaping('import time;time.sleep(3)', 'CANCELLED', cancel=True)

    def test_wall_limit_reaps_original_guardian(self):
        self.check_reaping('import time;time.sleep(3)', 'LIMIT_STOPPED', wall_seconds=.2)

    def test_service_exit_preserves_original_guardian_and_reopened_cancellation(self):
        # An isolated subreaper stands in for a functioning init. It adopts only
        # this controller's descendants, avoiding orphan zombies in test hosts
        # whose PID 1 does not reap. The test runner's process state is untouched.
        controller = textwrap.dedent('''\
            import json, sys, time
            from pathlib import Path
            from agent_factory.process_enforcement import BoundedProcessAdapter, ProcessLimits, ProcessSpec
            path, executable, sha = sys.argv[1:]
            adapter = BoundedProcessAdapter.create(Path(path), owner_id='alice', task_id='task1', request_id='request1',
                spec=ProcessSpec(executable, sha, ('-I', '-c', 'import time;time.sleep(20)')),
                limits=ProcessLimits(wall_seconds=5))
            adapter.launch(owner_id='alice', before_effect=lambda: None)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                facts = adapter.inspect(owner_id='alice')
                if facts['state'] == 'RUNNING':
                    print(json.dumps(facts), flush=True)
                    break
                time.sleep(.01)
            else:
                raise AssertionError('guardian never started')
            # Normal interpreter exit must not join the daemon reaper.
            ''')
        supervisor = textwrap.dedent('''\
            import ctypes, json, os, subprocess, sys, time
            from agent_factory.process_enforcement import BoundedProcessAdapter, ProcessEnforcementError, birth, same_birth
            path, executable, sha, controller = sys.argv[1:]
            libc = ctypes.CDLL(None, use_errno=True)
            assert libc.prctl(36, 1, 0, 0, 0) == 0, 'PR_SET_CHILD_SUBREAPER failed'
            child = subprocess.Popen([sys.executable, '-c', controller, path, executable, sha],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            reopened = None
            original = None
            try:
                stdout, stderr = child.communicate(timeout=3)
                assert child.returncode == 0, stderr
                original = json.loads(stdout)
                reopened = BoundedProcessAdapter(path)
                current = reopened.inspect(owner_id='alice')
                assert current['state'] == 'RUNNING', current
                assert current['capacityHeld'] and not current['stoppedProof']
                assert current['guardian'] == original['guardian']
                assert current['child'] == original['child']
                assert same_birth(birth(original['guardian']['pid']), original['guardian'])
                try:
                    reopened.launch(owner_id='alice', before_effect=lambda: None)
                except ProcessEnforcementError:
                    pass
                else:
                    raise AssertionError('reopened adapter dispatched again')
                reopened.cancel(owner_id='alice')
                stopped = reopened.wait(owner_id='alice')
                assert stopped['state'] == 'CANCELLED' and stopped['stoppedProof'], stopped
                assert not stopped['capacityHeld']
                for key in ('id', 'identitySha256', 'guardian', 'child'):
                    assert stopped[key] == original[key], key
                print(json.dumps({'controllerExit': child.returncode, 'state': stopped['state'],
                    'stoppedProof': stopped['stoppedProof']}))
            finally:
                # Only original custody cancellation; never signal arbitrary PIDs.
                if reopened is None and os.path.exists(path):
                    reopened = BoundedProcessAdapter(path)
                if reopened is not None:
                    reopened.cancel(owner_id='alice')
                    facts = reopened.wait(owner_id='alice', timeout=10)
                    original = original or facts
                child.wait(timeout=10)
                guardian = (original or {}).get('guardian')
                if guardian:
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline:
                        pid, _ = os.waitpid(guardian['pid'], os.WNOHANG)
                        if pid == guardian['pid']:
                            break
                        time.sleep(.01)
                    else:
                        raise AssertionError('original adopted guardian not reaped')
            ''')
        result = subprocess.run([sys.executable, '-c', supervisor, str(self.path), self.executable,
            self.sha, controller], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
            {'controllerExit': 0, 'state': 'CANCELLED', 'stoppedProof': True})
