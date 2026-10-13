"""Real local subprocesses only; all credentials/output fixtures are synthetic."""
import asyncio
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_factory._personal_cli_process import CLIProcessError, _group_stopped, _stop, run_cli_process


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
            while not path.exists():
                await asyncio.sleep(.01)
        return json.loads(path.read_text())

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


if __name__ == '__main__':
    unittest.main()
