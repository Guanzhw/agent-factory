"""Real local subprocesses only; all credentials/output fixtures are synthetic."""
import asyncio
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import time
from typing import Any
import unittest
from unittest.mock import patch

from agent_factory import _personal_cli_process as cli_process
from agent_factory._personal_cli_process import (
    CLIProcessError, _group_stopped, _run_windows_cli_process, _stop, _stop_windows, run_cli_process,
)
from agent_factory.windows_ssh_process import WindowsProcessCreateError, WindowsSSHProcess


@unittest.skipUnless(os.name == 'posix', 'CLI subprocess groups require POSIX')
class PersonalCLIProcessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.checks = 0

    def authorize(self):
        self.checks += 1

    async def run_process(self, source, **options):
        return await run_cli_process(executable=sys.executable, argv=('-I', '-c', source), env={},
            cwd=self.root, stdin=b'', timeout_seconds=3, max_output_bytes=1024,
            before_spawn=lambda: None, check_authorized=self.authorize, **options)

    async def wait_file(self, path):
        async with asyncio.timeout(3):
            while True:
                try:
                    return json.loads(path.read_text())
                except (FileNotFoundError, json.JSONDecodeError):
                    # The subprocess publishes this small fixture directly;
                    # existence alone does not mean its JSON write has finished.
                    pass
                await asyncio.sleep(.01)

    async def test_explicit_environment_cwd_stdin_and_nonzero_exit_are_returned_without_output_repr(self):
        source = ('import json,os,sys; print(json.dumps({"environment":dict(os.environ),'
            '"cwd":os.getcwd(),"stdin":sys.stdin.read()})); '
            'print("synthetic stderr",file=sys.stderr);sys.exit(17)')
        with patch.dict(os.environ, {'PERSONAL_CLI_HOST_SECRET': 'synthetic-host-value'}):
            result = await run_cli_process(executable=sys.executable, argv=('-I', '-c', source),
                env={'EXPLICIT': 'fixture', 'LC_ALL': 'C'}, cwd=self.root, stdin=b'synthetic-input',
                timeout_seconds=3, max_output_bytes=1024, before_spawn=lambda: None,
                check_authorized=self.authorize)
        value = json.loads(result.stdout)
        self.assertEqual(value, {'environment': {'EXPLICIT': 'fixture', 'LC_ALL': 'C'},
            'cwd': str(self.root), 'stdin': 'synthetic-input'})
        self.assertEqual(result.stderr, b'synthetic stderr\n')
        self.assertEqual(result.returncode, 17)
        self.assertTrue(result.dispatched and result.stopped)
        self.assertNotIn('synthetic', repr(result))
        self.assertGreaterEqual(self.checks, 2)

    async def test_owner_check_runs_after_async_before_spawn_and_prevents_dispatch(self):
        before_finished = False
        async def before():
            nonlocal before_finished
            await asyncio.sleep(0)
            before_finished = True
        def denied():
            self.assertTrue(before_finished)
            raise RuntimeError('synthetic private owner error')
        with patch('asyncio.create_subprocess_exec') as spawn:
            with self.assertRaises(CLIProcessError) as caught:
                await run_cli_process(executable=sys.executable, argv=(), env={}, cwd=self.root, stdin=b'',
                    timeout_seconds=1, max_output_bytes=100, before_spawn=before, check_authorized=denied)
        spawn.assert_not_called()
        self.assertFalse(caught.exception.dispatched)
        self.assertEqual(caught.exception.outcome, 'failed')
        self.assertTrue(caught.exception.stopped)
        self.assertNotIn('private', str(caught.exception))

    async def test_spawn_failure_is_sanitized_and_not_dispatched(self):
        with self.assertRaises(CLIProcessError) as caught:
            await run_cli_process(executable=str(self.root / 'missing-synthetic-secret'), argv=(), env={},
                cwd=self.root, stdin=b'', timeout_seconds=1, max_output_bytes=100,
                before_spawn=lambda: None, check_authorized=self.authorize)
        self.assertFalse(caught.exception.dispatched)
        self.assertEqual(caught.exception.outcome, 'failed')
        self.assertTrue(caught.exception.stopped)
        self.assertNotIn('synthetic-secret', repr(caught.exception))

    async def test_unclassified_spawn_failure_cannot_claim_no_dispatch_or_local_stop(self):
        async def unconfirmed(*args, **kwargs):
            raise RuntimeError('synthetic private spawn state')
        with patch('asyncio.create_subprocess_exec', unconfirmed):
            with self.assertRaises(CLIProcessError) as caught:
                await self.run_process('pass')
        self.assertEqual(caught.exception.code, 'PERSONAL_CLI_SPAWN_UNCONFIRMED')
        self.assertEqual(caught.exception.outcome, 'unknown')
        self.assertTrue(caught.exception.dispatched)
        self.assertFalse(caught.exception.stopped)
        self.assertNotIn('private', str(caught.exception))

    async def test_stdout_and_stderr_share_one_output_limit(self):
        source = 'import os,time;os.write(1,b"a"*600);os.write(2,b"b"*600);time.sleep(10)'
        with self.assertRaises(CLIProcessError) as caught:
            await self.run_process(source)
        self.assertEqual(caught.exception.code, 'PERSONAL_CLI_OUTPUT_LIMIT')
        self.assertEqual(caught.exception.outcome, 'unknown')
        self.assertTrue(caught.exception.dispatched and caught.exception.stopped)

    async def test_both_pipes_flooding_keep_every_read_positive_and_bounded(self):
        source = ('import os,threading; '
            '\ndef flood(fd):\n while True: os.write(fd,b"x"*65536)'
            '\nthreading.Thread(target=flood,args=(1,),daemon=True).start();flood(2)')
        original_read = asyncio.StreamReader.read
        sizes = []
        async def bounded_read(reader, size=-1):
            sizes.append(size)
            return await original_read(reader, size)
        with patch.object(asyncio.StreamReader, 'read', bounded_read):
            with self.assertRaises(CLIProcessError) as caught:
                await self.run_process(source)
        self.assertEqual(caught.exception.code, 'PERSONAL_CLI_OUTPUT_LIMIT')
        self.assertTrue(caught.exception.stopped)
        self.assertTrue(sizes)
        self.assertTrue(all(0 < size <= 65536 for size in sizes))

    def group_source(self, *, parent_exits=False):
        state = self.root / 'state.json'
        source = ('import json,os,signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);pid=os.fork();'
            '\nif pid==0:\n time.sleep(10);os._exit(0)'
            '\nelse:\n open(' + repr(str(state)) + ',"w").write(json.dumps({"pid":os.getpid(),"child":pid}));'
            + ('os._exit(0)' if parent_exits else 'time.sleep(10)'))
        return state, source

    async def test_cancellation_kills_ignoring_parent_and_child_before_returning(self):
        state, source = self.group_source()
        task = asyncio.create_task(self.run_process(source))
        identity = await self.wait_file(state)
        task.cancel()
        await asyncio.sleep(.03)
        task.cancel()  # Cleanup remains owned despite repeated cancellation.
        with self.assertRaises(CLIProcessError) as caught:
            await task
        self.assertEqual(caught.exception.outcome, 'cancelled')
        self.assertTrue(caught.exception.dispatched and caught.exception.stopped)
        self.assertTrue(_group_stopped(identity['pid']))

    async def test_parent_exit_does_not_leave_ignoring_child_or_inherited_output_pipe(self):
        state, source = self.group_source(parent_exits=True)
        result = await self.run_process(source)
        identity = json.loads(state.read_text())
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stopped)
        self.assertTrue(_group_stopped(identity['pid']))

    async def test_timeout_and_runtime_authority_loss_stop_group_but_outcome_remains_unknown(self):
        for reason in ('timeout', 'authority'):
            with self.subTest(reason=reason):
                state, source = self.group_source()
                state.unlink(missing_ok=True)
                def check():
                    if reason == 'authority' and state.exists():
                        raise RuntimeError('synthetic secret must not escape')
                with self.assertRaises(CLIProcessError) as caught:
                    await run_cli_process(executable=sys.executable, argv=('-I', '-c', source), env={},
                        cwd=self.root, stdin=b'', timeout_seconds=.15 if reason == 'timeout' else 3,
                        max_output_bytes=1024, before_spawn=lambda: None, check_authorized=check)
                identity = json.loads(state.read_text())
                self.assertEqual(caught.exception.outcome, 'unknown')
                self.assertTrue(caught.exception.stopped and caught.exception.dispatched)
                self.assertTrue(_group_stopped(identity['pid']))

    async def test_cancellation_during_spawn_waits_for_custody_then_stops_group(self):
        real_spawn = asyncio.create_subprocess_exec
        spawned, deliver = asyncio.Event(), asyncio.Event()
        identity = []
        async def delayed_spawn(*args, **kwargs):
            process = await real_spawn(*args, **kwargs)
            identity.append(process.pid)
            spawned.set()
            await deliver.wait()
            return process
        with patch('asyncio.create_subprocess_exec', delayed_spawn):
            task = asyncio.create_task(self.run_process('import time;time.sleep(10)'))
            await spawned.wait()
            task.cancel()
            await asyncio.sleep(.03)
            self.assertFalse(task.done())
            deliver.set()
            with self.assertRaises(CLIProcessError) as caught:
                await task
        self.assertEqual(caught.exception.outcome, 'cancelled')
        self.assertTrue(caught.exception.stopped and caught.exception.dispatched)
        self.assertTrue(_group_stopped(identity[0]))

    async def test_cancellation_during_async_guard_prevents_spawn(self):
        entered = asyncio.Event()
        async def before():
            entered.set()
            await asyncio.Event().wait()
        with patch('asyncio.create_subprocess_exec') as spawn:
            task = asyncio.create_task(run_cli_process(executable=sys.executable, argv=(), env={},
                cwd=self.root, stdin=b'', timeout_seconds=3, max_output_bytes=100,
                before_spawn=before, check_authorized=self.authorize))
            await entered.wait()
            task.cancel()
            with self.assertRaises(CLIProcessError) as caught:
                await task
        spawn.assert_not_called()
        self.assertFalse(caught.exception.dispatched)
        self.assertEqual(caught.exception.outcome, 'cancelled')
        self.assertTrue(caught.exception.stopped)

    async def test_cancellation_during_normal_cleanup_does_not_return_success(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed_stop(process):
            entered.set()
            await release.wait()
            return await _stop(process)
        with patch('agent_factory._personal_cli_process._stop', delayed_stop):
            task = asyncio.create_task(self.run_process('pass'))
            await entered.wait()
            task.cancel()
            await asyncio.sleep(.02)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(CLIProcessError) as caught:
                await task
        self.assertEqual(caught.exception.outcome, 'cancelled')
        self.assertTrue(caught.exception.dispatched and caught.exception.stopped)

    async def test_unverified_group_stop_is_unknown_and_does_not_release_custody(self):
        with patch('agent_factory._personal_cli_process._group_stopped', return_value=False):
            with self.assertRaises(CLIProcessError) as caught:
                await self.run_process('pass')
        self.assertEqual(caught.exception.code, 'PERSONAL_CLI_STOP_UNCONFIRMED')
        self.assertEqual(caught.exception.outcome, 'unknown')
        self.assertTrue(caught.exception.dispatched)
        self.assertFalse(caught.exception.stopped)


class WindowsCLIProtocolTests(unittest.IsolatedAsyncioTestCase):
    """Portable protocol doubles; these do not verify Windows handles or Jobs."""

    class Process:
        def __init__(self, args, env, *, cwd, capture_stderr):
            self.events = []
            self.resumed = self.killed = self.closed = False
            self.returncode = None
            self.job_count = 0
            self.job_error = False
            input_read, input_write = os.pipe()
            self.input_read = input_read
            self.stdin = os.fdopen(input_write, 'wb', buffering=0)
            output_read, output_write = os.pipe()
            self.stdout = os.fdopen(output_read, 'rb', buffering=0)
            os.write(output_write, b'out')
            os.close(output_write)
            error_read, error_write = os.pipe()
            self.stderr = os.fdopen(error_read, 'rb', buffering=0)
            os.write(error_write, b'err')
            os.close(error_write)

        def resume(self):
            self.events.append('resume')
            self.resumed = True
            self.returncode = 17

        def poll(self):
            return self.returncode

        def kill(self):
            self.events.append('kill')
            self.killed = True
            if self.returncode is None:
                self.returncode = 1

        def job_active_processes(self):
            self.events.append('query')
            if self.job_error:
                raise RuntimeError('private native error')
            value = self.job_count
            self.job_count = 0
            return value

        def close(self):
            self.events.append('close')
            self.closed = True
            for stream in (self.stdin, self.stdout, self.stderr):
                stream.close()
            os.close(self.input_read)

    async def run_process(self, **options):
        arguments: dict[str, Any] = dict(executable=sys.executable, argv=(), env={}, cwd=Path.cwd(), stdin=b'',
            timeout_seconds=3, max_output_bytes=1024, before_spawn=lambda: None,
            check_authorized=lambda: None)
        arguments.update(options)
        return await _run_windows_cli_process(**arguments)

    async def test_guard_is_awaited_and_current_authority_is_checked_before_resume(self):
        events, processes = [], []
        async def before():
            await asyncio.sleep(0)
            events.append('before')
        def authorize():
            events.append('check')
            if processes:
                raise RuntimeError('private authority loss')
        def construct(*args, **kwargs):
            events.append('create')
            process = self.Process(*args, **kwargs)
            processes.append(process)
            return process
        with patch('agent_factory._personal_cli_process.WindowsSSHProcess', construct):
            with self.assertRaises(CLIProcessError) as caught:
                await self.run_process(before_spawn=before, check_authorized=authorize)
        self.assertEqual(events, ['before', 'check', 'create', 'check'])
        self.assertFalse(processes[0].resumed)
        self.assertTrue(processes[0].killed and processes[0].closed)
        self.assertFalse(caught.exception.dispatched)
        self.assertTrue(caught.exception.stopped)
        self.assertNotIn('private', str(caught.exception))

    async def test_cancellation_during_creation_recovers_suspended_owner_without_resume(self):
        entered, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        processes = []
        def construct(*args, **kwargs):
            process = self.Process(*args, **kwargs)
            processes.append(process)
            loop.call_soon_threadsafe(entered.set)
            release.wait(timeout=5)
            return process
        with patch('agent_factory._personal_cli_process.WindowsSSHProcess', construct):
            task = asyncio.create_task(self.run_process())
            try:
                await entered.wait()
                task.cancel()
                await asyncio.sleep(.02)
                task.cancel()
                await asyncio.sleep(.02)
                self.assertFalse(task.done())
            finally:
                release.set()
            with self.assertRaises(CLIProcessError) as caught:
                await task
        self.assertFalse(processes[0].resumed)
        self.assertTrue(processes[0].closed)
        self.assertEqual(caught.exception.outcome, 'cancelled')
        self.assertFalse(caught.exception.dispatched)
        self.assertTrue(caught.exception.stopped)

    async def test_cancellation_during_async_guard_never_creates_process(self):
        entered = asyncio.Event()
        async def before():
            entered.set()
            await asyncio.Event().wait()
        with patch('agent_factory._personal_cli_process.WindowsSSHProcess', side_effect=self.Process) as constructor:
            task = asyncio.create_task(self.run_process(before_spawn=before))
            await entered.wait()
            task.cancel()
            with self.assertRaises(CLIProcessError) as caught:
                await task
        constructor.assert_not_called()
        self.assertEqual(caught.exception.outcome, 'cancelled')
        self.assertFalse(caught.exception.dispatched)
        self.assertTrue(caught.exception.stopped)

    async def test_synchronous_authority_check_cannot_resume_after_deadline(self):
        processes = []
        def construct(*args, **kwargs):
            process = self.Process(*args, **kwargs)
            processes.append(process)
            return process
        def check():
            if processes:
                time.sleep(.15)
        with patch('agent_factory._personal_cli_process.WindowsSSHProcess', construct):
            with self.assertRaises(CLIProcessError) as caught:
                await self.run_process(check_authorized=check, timeout_seconds=.1)
        self.assertFalse(processes[0].resumed)
        self.assertEqual(caught.exception.code, 'PERSONAL_CLI_TIMEOUT')
        self.assertFalse(caught.exception.dispatched)
        self.assertTrue(caught.exception.stopped)

    async def test_creation_error_only_releases_custody_when_suspended_cleanup_is_confirmed(self):
        for error, stopped in ((WindowsProcessCreateError('private create'), True),
                               (RuntimeError('private cleanup'), False)):
            with self.subTest(stopped=stopped):
                with patch('agent_factory._personal_cli_process.WindowsSSHProcess', side_effect=error):
                    with self.assertRaises(CLIProcessError) as caught:
                        await self.run_process()
                self.assertEqual(caught.exception.stopped, stopped)
                self.assertEqual(caught.exception.dispatched, not stopped)
                self.assertEqual(caught.exception.outcome, 'failed' if stopped else 'unknown')
                self.assertNotIn('private', str(caught.exception))

    async def test_original_job_is_observed_before_close_and_nonzero_result_is_returned(self):
        processes = []
        def construct(*args, **kwargs):
            process = self.Process(*args, **kwargs)
            process.job_count = 1
            processes.append(process)
            return process
        with patch('agent_factory._personal_cli_process.WindowsSSHProcess', construct):
            result = await self.run_process()
        self.assertEqual((result.stdout, result.stderr, result.returncode), (b'out', b'err', 17))
        self.assertEqual(processes[0].events, ['resume', 'kill', 'query', 'query', 'close'])
        self.assertTrue(result.dispatched and result.stopped)

    async def test_failed_job_observation_stays_unknown_even_when_root_exited_and_close_succeeds(self):
        processes = []
        def construct(*args, **kwargs):
            process = self.Process(*args, **kwargs)
            process.job_error = True
            processes.append(process)
            return process
        with patch('agent_factory._personal_cli_process.WindowsSSHProcess', construct):
            with self.assertRaises(CLIProcessError) as caught:
                await self.run_process()
        self.assertTrue(processes[0].closed)
        self.assertEqual(caught.exception.code, 'PERSONAL_CLI_STOP_UNCONFIRMED')
        self.assertEqual(caught.exception.outcome, 'unknown')
        self.assertFalse(caught.exception.stopped)

    async def test_repeated_cancel_during_cleanup_does_not_return_success(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed_stop(process):
            entered.set()
            await release.wait()
            return await _stop_windows(process)
        with (patch('agent_factory._personal_cli_process.WindowsSSHProcess', self.Process),
              patch('agent_factory._personal_cli_process._stop_windows', delayed_stop)):
            task = asyncio.create_task(self.run_process())
            await entered.wait()
            task.cancel()
            await asyncio.sleep(.02)
            task.cancel()
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(CLIProcessError) as caught:
                await task
        self.assertEqual(caught.exception.outcome, 'cancelled')
        self.assertTrue(caught.exception.stopped and caught.exception.dispatched)

    async def test_output_budget_is_shared_across_streams(self):
        with patch('agent_factory._personal_cli_process.WindowsSSHProcess', self.Process):
            with self.assertRaises(CLIProcessError) as caught:
                await self.run_process(max_output_bytes=5)
        self.assertEqual(caught.exception.code, 'PERSONAL_CLI_OUTPUT_LIMIT')
        self.assertTrue(caught.exception.stopped and caught.exception.dispatched)


@unittest.skipUnless(sys.platform == 'win32', 'Requires actual Windows CLI, pipes and original Job APIs')
class WindowsCLIProcessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = TemporaryDirectory(prefix='research 中文 ')
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.observations = []
        native = WindowsSSHProcess
        observations = self.observations
        class ObservedProcess(native):
            def job_active_processes(self):
                # Record the actual original Job query before its owner closes
                # the handle; root PID disappearance is not this evidence.
                value = super().job_active_processes()
                assert self._job is not None
                observations.append((int(self._job), value))
                return value
        self.patch = patch('agent_factory._personal_cli_process.WindowsSSHProcess', ObservedProcess)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    async def run_process(self, source, **options):
        arguments: dict[str, Any] = dict(executable=sys.executable, argv=('-I', '-X', 'utf8', '-c', source),
            env={'SystemRoot': os.environ['SystemRoot']}, cwd=self.root, stdin=b'',
            timeout_seconds=5, max_output_bytes=1024, before_spawn=lambda: None,
            check_authorized=lambda: None)
        arguments.update(options)
        return await run_cli_process(**arguments)

    def assert_job_stopped(self):
        self.assertTrue(self.observations)
        self.assertEqual(self.observations[-1][1], 0)
        self.assertEqual(len({job for job, _ in self.observations}), 1)

    async def wait_file(self, path):
        async with asyncio.timeout(5):
            while not path.exists():
                await asyncio.sleep(.01)

    async def test_exact_argv_cwd_environment_stdin_stderr_and_nonzero(self):
        arguments = ['中文 空格', 'a"b', 'c\\', '& echo must-stay-an-argument']
        source = ('import json,os,sys; print(json.dumps({"argv":sys.argv[1:],"cwd":os.getcwd(),'
            '"input":sys.stdin.read(),"secret":os.getenv("PERSONAL_CLI_HOST_SECRET")}));'
            'sys.stderr.buffer.write("错误".encode());sys.exit(17)')
        with patch.dict(os.environ, {'PERSONAL_CLI_HOST_SECRET': 'synthetic-host-value'}):
            result = await self.run_process(source, argv=('-I', '-X', 'utf8', '-c', source, *arguments),
                stdin='输入'.encode())
        self.assertEqual(json.loads(result.stdout), {'argv': arguments, 'cwd': str(self.root),
            'input': '输入', 'secret': None})
        self.assertEqual(result.stderr, '错误'.encode())
        self.assertEqual(result.returncode, 17)
        self.assert_job_stopped()

    async def test_three_streams_larger_than_pipe_capacity_make_progress(self):
        source = ('import os,sys,threading; '
            '\ndef send(fd,byte):\n for _ in range(128): os.write(fd,byte*4096)'
            '\na=threading.Thread(target=send,args=(1,b"a"));'
            'b=threading.Thread(target=send,args=(2,b"b"));a.start();b.start();'
            'payload=sys.stdin.buffer.read();a.join();b.join();'
            'os.write(1,str(len(payload)).encode())')
        result = await self.run_process(source, stdin=b'x' * (512 * 1024),
            max_output_bytes=2 * 1024 * 1024, timeout_seconds=15)
        self.assertEqual(result.stdout, b'a' * (512 * 1024) + b'524288')
        self.assertEqual(result.stderr, b'b' * (512 * 1024))
        self.assert_job_stopped()

    def child_source(self, *, parent_exits=False):
        marker = self.root / 'started'
        source = ('import subprocess,sys,pathlib,time; subprocess.Popen([sys.executable,"-I","-c",'
            '"import time;time.sleep(60)"]); pathlib.Path(' + repr(str(marker)) + ').touch();'
            + ('sys.exit(0)' if parent_exits else 'time.sleep(60)'))
        return marker, source

    async def test_root_exit_does_not_wait_forever_for_child_inherited_pipes(self):
        _, source = self.child_source(parent_exits=True)
        result = await self.run_process(source)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stopped)
        self.assert_job_stopped()

    async def test_repeated_cancellation_stops_original_job(self):
        marker, source = self.child_source()
        task = asyncio.create_task(self.run_process(source))
        await self.wait_file(marker)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(CLIProcessError) as caught:
            await task
        self.assertEqual(caught.exception.outcome, 'cancelled')
        self.assertTrue(caught.exception.stopped and caught.exception.dispatched)
        self.assert_job_stopped()

    async def test_timeout_authority_loss_and_output_limit_keep_unknown_effect(self):
        for reason in ('timeout', 'authority', 'output'):
            with self.subTest(reason=reason):
                self.observations.clear()
                marker, source = self.child_source()
                marker.unlink(missing_ok=True)
                if reason == 'output':
                    source = 'import os,time; os.write(1,b"x"*600);os.write(2,b"y"*600);time.sleep(60)'
                def check():
                    if reason == 'authority' and marker.exists():
                        raise RuntimeError('synthetic private authority error')
                with self.assertRaises(CLIProcessError) as caught:
                    await self.run_process(source, timeout_seconds=.5 if reason == 'timeout' else 5,
                        check_authorized=check)
                self.assertEqual(caught.exception.outcome, 'unknown')
                self.assertTrue(caught.exception.stopped and caught.exception.dispatched)
                self.assert_job_stopped()

    async def test_creation_cancel_never_resumes_late_suspended_child(self):
        entered, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        observed_class = cli_process.WindowsSSHProcess
        marker = self.root / 'must-not-run'
        processes = []
        def delayed(*args, **kwargs):
            process = observed_class(*args, **kwargs)
            processes.append(process)
            loop.call_soon_threadsafe(entered.set)
            release.wait(timeout=5)
            return process
        with patch('agent_factory._personal_cli_process.WindowsSSHProcess', delayed):
            task = asyncio.create_task(self.run_process('from pathlib import Path;Path(' + repr(str(marker)) + ').touch()'))
            try:
                await entered.wait()
                task.cancel()
                await asyncio.sleep(.02)
                self.assertFalse(task.done())
            finally:
                release.set()
            with self.assertRaises(CLIProcessError) as caught:
                await task
        self.assertFalse(marker.exists())
        self.assertFalse(processes[0]._resumed)
        self.assertTrue(processes[0]._closed)
        self.assertFalse(caught.exception.dispatched)
        self.assertTrue(caught.exception.stopped)
        self.assert_job_stopped()

    async def test_configured_budget_allows_test_longer_than_thirty_seconds(self):
        result = await self.run_process('import time;time.sleep(30.1);print("finished")', timeout_seconds=40)
        self.assertEqual(result.stdout.strip(), b'finished')
        self.assertEqual(result.returncode, 0)
        self.assert_job_stopped()


if __name__ == '__main__':
    unittest.main()
