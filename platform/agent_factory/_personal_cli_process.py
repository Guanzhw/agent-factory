"""Invocation-owned POSIX groups or Windows Jobs; no shell or ambient environment.

Stop evidence covers the owned local tree, not remote effects or processes that
escape its ownership. Output and argv never become error diagnostics.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
import errno
import inspect
import math
import os
from pathlib import Path
import signal
import sys
from typing import Any

from .personal_tool_contract import ToolInvocationError
from .windows_ssh_process import WindowsProcessCreateError, WindowsSSHProcess


@dataclass(frozen=True)
class CLIProcessResult:
    stdout: bytes = field(repr=False)
    stderr: bytes = field(repr=False)
    returncode: int
    dispatched: bool = True
    stopped: bool = True


class CLIProcessError(ToolInvocationError):
    def __init__(self, code: str, *, dispatched: bool, stopped: bool, cancelled: bool = False):
        outcome = 'cancelled' if cancelled and stopped else 'unknown' if dispatched or not stopped else 'failed'
        super().__init__(code, outcome=outcome, stopped=stopped)
        self.dispatched = dispatched


class _OutputLimit(Exception):
    pass


def _group_stopped(group: int) -> bool:
    if sys.platform == 'win32':
        raise RuntimeError('CLI_PLATFORM_UNAVAILABLE')
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    if sys.platform != 'linux':
        return False
    # Orphaned zombies can remain until their new parent reaps them. They can
    # no longer execute; never mistake killpg(0)'s existence check for liveness.
    try:
        for entry in Path('/proc').iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                stat = (entry / 'stat').read_text()
            except FileNotFoundError:
                continue
            fields = stat[stat.rfind(')') + 2:].split()
            if int(fields[2]) == group and fields[0] not in {'Z', 'X'}:
                return False
    except (OSError, ValueError, IndexError):
        return False
    return True


async def _settle(task: asyncio.Task[Any], on_cancel: Callable[[], None]):
    """Finish owned cleanup even if the caller requests cancellation again."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            on_cancel()
            continue
        except Exception:
            break
    return task.result()


async def _stop(process: asyncio.subprocess.Process) -> bool:
    if sys.platform == 'win32':
        raise RuntimeError('CLI_PLATFORM_UNAVAILABLE')
    for sig, grace in ((signal.SIGTERM, .2), (signal.SIGKILL, 1.0)):
        if _group_stopped(process.pid) and process.returncode is not None:
            return True
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except OSError:
            return False
        deadline = asyncio.get_running_loop().time() + grace
        while asyncio.get_running_loop().time() < deadline:
            if _group_stopped(process.pid) and process.returncode is not None:
                return True
            await asyncio.sleep(.02)
    return _group_stopped(process.pid) and process.returncode is not None


async def _stop_windows(process: WindowsSSHProcess) -> bool:
    process.kill()
    deadline = asyncio.get_running_loop().time() + 5
    while True:
        if process.poll() is not None and process.job_active_processes() == 0:
            return True
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(.02)


async def _run_windows_cli_process(*, executable: str, argv: Sequence[str], env: Mapping[str, str],
        cwd: str | Path, stdin: bytes, timeout_seconds: float, max_output_bytes: int,
        before_spawn: Callable[[], None | Awaitable[None]], check_authorized: Callable[[], None]) -> CLIProcessResult:
    process = None
    creating = rejected = dispatched = False
    code, cancelled = None, False
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    buffers = [bytearray(), bytearray()]
    eof = [False, False]
    pending = memoryview(stdin)
    total = 0

    async def spawn():
        nonlocal creating, rejected
        checked = before_spawn()
        if inspect.isawaitable(checked):
            await checked
        check_authorized()
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError()
        creating = True
        try:
            return await asyncio.to_thread(WindowsSSHProcess, [executable, *argv], dict(env),
                cwd=str(cwd), capture_stderr=True)
        except WindowsProcessCreateError:
            rejected = True
            raise

    def read_output():
        nonlocal total
        assert process is not None
        for index, stream in enumerate((process.stdout, process.stderr)):
            assert stream is not None
            if eof[index]:
                continue
            try:
                chunk = os.read(stream.fileno(), min(65536, max_output_bytes - total + 1))
            except BlockingIOError:
                continue
            if total + len(chunk) > max_output_bytes:
                raise _OutputLimit()
            total += len(chunk)
            buffers[index].extend(chunk)
            eof[index] = not chunk

    def mark_cancelled():
        nonlocal code, cancelled
        if code is None:
            code, cancelled = 'PERSONAL_CLI_CANCELLED', True

    spawn_task = asyncio.create_task(spawn())
    try:
        async with asyncio.timeout_at(deadline):
            process = await asyncio.shield(spawn_task)
            assert process.stdin is not None and process.stdout is not None and process.stderr is not None
            for stream in (process.stdin, process.stdout, process.stderr):
                os.set_blocking(stream.fileno(), False)
            # The child remains suspended until custody and current authority
            # are both known. Timeout/cancellation never resumes a late child.
            check_authorized()
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError()
            dispatched = True
            process.resume()
            while True:
                check_authorized()
                read_output()
                if not process.stdin.closed:
                    try:
                        if pending:
                            count = os.write(process.stdin.fileno(), pending[:4096])
                            pending = pending[count:]
                        else:
                            process.stdin.close()
                    except BlockingIOError:
                        pass
                    except (BrokenPipeError, ConnectionResetError):
                        process.stdin.close()
                if process.poll() is not None:
                    break
                await asyncio.sleep(.01)
    except asyncio.CancelledError:
        code, cancelled = 'PERSONAL_CLI_CANCELLED', True
    except TimeoutError:
        code = 'PERSONAL_CLI_TIMEOUT'
    except _OutputLimit:
        code = 'PERSONAL_CLI_OUTPUT_LIMIT'
    except Exception:
        code = 'PERSONAL_CLI_PROCESS_FAILED'

    if process is None:
        if not creating:
            spawn_task.cancel()
        try:
            process = await _settle(spawn_task, mark_cancelled)
        except (asyncio.CancelledError, Exception):
            pass
    if process is None and creating and not rejected:
        raise CLIProcessError('PERSONAL_CLI_SPAWN_UNCONFIRMED', dispatched=True, stopped=False) from None
    stopped = True
    if process is not None:
        try:
            stopped = await _settle(asyncio.create_task(_stop_windows(process)), mark_cancelled)
            if stopped and code is None:
                async def drain():
                    async with asyncio.timeout(.5):
                        while not all(eof):
                            read_output()
                            if not all(eof):
                                await asyncio.sleep(.01)
                await _settle(asyncio.create_task(drain()), mark_cancelled)
        except _OutputLimit:
            code = 'PERSONAL_CLI_OUTPUT_LIMIT'
        except Exception:
            stopped = False
        finally:
            try:
                # Even when observation failed, close the original Job and its
                # pipes. KILL_ON_JOB_CLOSE is cleanup, not stop confirmation.
                await _settle(asyncio.create_task(asyncio.to_thread(process.close)), mark_cancelled)
            except Exception:
                stopped = False
    if not stopped:
        raise CLIProcessError('PERSONAL_CLI_STOP_UNCONFIRMED', dispatched=dispatched, stopped=False) from None
    if code is not None or process is None:
        raise CLIProcessError(code or 'PERSONAL_CLI_PROCESS_FAILED', dispatched=dispatched,
            stopped=True, cancelled=cancelled) from None
    assert process.returncode is not None
    return CLIProcessResult(bytes(buffers[0]), bytes(buffers[1]), process.returncode)


async def run_cli_process(*, executable: str, argv: Sequence[str], env: Mapping[str, str],
        cwd: str | Path, stdin: bytes, timeout_seconds: float, max_output_bytes: int,
        before_spawn: Callable[[], None | Awaitable[None]], check_authorized: Callable[[], None]) -> CLIProcessResult:
    """Run once; a nonzero exit is returned for the adapter to interpret.

    Cancellation waits for spawn custody and group cleanup before raising a
    sanitized ToolInvocationError. Other errors after dispatch remain UNKNOWN,
    even when the local group has been stopped successfully.
    """
    if (os.name not in {'posix', 'nt'} or type(executable) is not str or not os.path.isabs(executable)
            or '\0' in executable or not isinstance(cwd, (str, Path)) or not os.path.isabs(cwd)
            or not isinstance(argv, Sequence) or isinstance(argv, (str, bytes))
            or any(type(arg) is not str or '\0' in arg for arg in argv)
            or not isinstance(env, Mapping) or any(type(key) is not str or type(value) is not str
                or '=' in key or '\0' in key or '\0' in value for key, value in env.items())
            or type(stdin) is not bytes or type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds) or timeout_seconds <= 0
            or type(max_output_bytes) is not int or max_output_bytes <= 0):
        raise CLIProcessError('PERSONAL_CLI_PROCESS_INVALID', dispatched=False, stopped=True)
    if sys.platform == 'win32':
        return await _run_windows_cli_process(executable=executable, argv=argv, env=env, cwd=cwd,
            stdin=stdin, timeout_seconds=timeout_seconds, max_output_bytes=max_output_bytes,
            before_spawn=before_spawn, check_authorized=check_authorized)
    process = None
    started = False
    spawn_rejected = False
    abort_spawn = False
    readers: list[asyncio.Task] = []
    buffers = [bytearray(), bytearray()]
    total = 0
    deadline = asyncio.get_running_loop().time() + timeout_seconds

    async def spawn():
        nonlocal started, spawn_rejected
        checked = before_spawn()
        if inspect.isawaitable(checked):
            await checked
        if abort_spawn:
            raise asyncio.CancelledError()
        check_authorized()
        started = True
        try:
            return await asyncio.create_subprocess_exec(executable, *argv, cwd=cwd, env=dict(env),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, start_new_session=True, close_fds=True)
        except OSError as error:
            # These are exec/cwd rejection outcomes. Other spawn failures may
            # occur after a child was started but before a handle was delivered.
            spawn_rejected = error.errno in {errno.ENOENT, errno.ENOTDIR, errno.EACCES, errno.ENOEXEC}
            raise

    async def read(stream: asyncio.StreamReader, index: int):
        nonlocal total
        while chunk := await stream.read(min(65536, max_output_bytes - total + 1)):
            if total + len(chunk) > max_output_bytes:
                raise _OutputLimit()
            total += len(chunk)
            buffers[index].extend(chunk)

    async def write():
        assert process is not None and process.stdin is not None
        try:
            process.stdin.write(stdin)
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            process.stdin.close()
        try:
            await process.stdin.wait_closed()
        except (BrokenPipeError, ConnectionResetError):
            pass

    spawn_task = asyncio.create_task(spawn())
    code, cancelled = None, False

    def mark_cancelled():
        nonlocal code, cancelled
        if code is None:
            code, cancelled = 'PERSONAL_CLI_CANCELLED', True

    try:
        async with asyncio.timeout_at(deadline):
            process = await asyncio.shield(spawn_task)
            assert process.stdout is not None and process.stderr is not None
            readers = [asyncio.create_task(read(process.stdout, 0)),
                asyncio.create_task(read(process.stderr, 1)), asyncio.create_task(write())]
            while True:
                check_authorized()
                for reader in readers:
                    if reader.done():
                        reader.result()
                if process.returncode is not None:
                    break
                await asyncio.sleep(.05)
    except asyncio.CancelledError:
        code, cancelled = 'PERSONAL_CLI_CANCELLED', True
    except TimeoutError:
        code = 'PERSONAL_CLI_TIMEOUT'
    except _OutputLimit:
        code = 'PERSONAL_CLI_OUTPUT_LIMIT'
    except Exception:
        code = 'PERSONAL_CLI_PROCESS_FAILED'

    # A shielded create_subprocess_exec may have started the child before its
    # Process handle was delivered. Never return until custody is recovered.
    if process is None:
        abort_spawn = True
        if not started:
            spawn_task.cancel()
        try:
            process = await _settle(spawn_task, mark_cancelled)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
    stopped = True
    if process is None and started and not spawn_rejected:
        raise CLIProcessError('PERSONAL_CLI_SPAWN_UNCONFIRMED', dispatched=True, stopped=False) from None
    if process is not None:
        try:
            stopped = await _settle(asyncio.create_task(_stop(process)), mark_cancelled)
        except Exception:
            stopped = False
        # Stop the group before cancelling pipe readers; inherited pipes must
        # not keep the invocation alive after the root process has exited.
        if stopped and code is None:
            try:
                async def drain():
                    async with asyncio.timeout(.5):
                        await asyncio.gather(*readers)
                await _settle(asyncio.create_task(drain()), mark_cancelled)
            except _OutputLimit:
                code = 'PERSONAL_CLI_OUTPUT_LIMIT'
            except Exception:
                code = 'PERSONAL_CLI_PROCESS_FAILED'
        for reader in readers:
            reader.cancel()
        if readers:
            async def close_readers():
                await asyncio.gather(*readers, return_exceptions=True)
            await _settle(asyncio.create_task(close_readers()), mark_cancelled)
        # Process exposes readers but no public method to close their owned
        # transports. Close these handles even if an escaped descendant kept a
        # pipe open; this is resource cleanup, never evidence of group stop.
        transport = getattr(process, '_transport', None)
        if transport is not None:
            try:
                transport.close()
            except Exception:
                code = code or 'PERSONAL_CLI_PROCESS_FAILED'
    if not stopped:
        raise CLIProcessError('PERSONAL_CLI_STOP_UNCONFIRMED', dispatched=process is not None, stopped=False)
    if code is not None or process is None:
        raise CLIProcessError(code or 'PERSONAL_CLI_PROCESS_FAILED', dispatched=process is not None,
            stopped=True, cancelled=cancelled) from None
    assert process.returncode is not None
    return CLIProcessResult(bytes(buffers[0]), bytes(buffers[1]), process.returncode)
