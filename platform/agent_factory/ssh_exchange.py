"""Bounded pipe exchange for the existing SSH subprocess owners (Python 3.12+)."""
from inspect import isawaitable, iscoroutine
import os
import subprocess
import time


class SSHExchangeCancelled(Exception):
    pass


class SSHExchangeCleanupError(RuntimeError):
    pass


def exchange(process, payload, *, deadline, max_output, before_write=None, cancelled=None):
    """Take pipe/reap ownership; caller owns spawn, Job and credential lifetime."""
    def checkpoint():
        if cancelled is not None and cancelled.is_set():
            raise SSHExchangeCancelled('SSH_EXCHANGE_CANCELLED')
        if time.monotonic() >= deadline:
            raise TimeoutError('SSH_EXCHANGE_TIMEOUT')

    def authorize():
        checkpoint()
        if before_write is not None:
            result = before_write()
            if isawaitable(result):
                if iscoroutine(result):
                    result.close()
                raise TypeError('SSH_EXCHANGE_SYNC_GUARD_REQUIRED')
        checkpoint()

    try:
        if not isinstance(payload, bytes) or len(payload) > 32768:
            raise ValueError('SSH_EXCHANGE_REQUEST_LIMIT')
        if type(max_output) is not int or not 1 <= max_output <= 1024 * 1024:
            raise ValueError('SSH_EXCHANGE_RESPONSE_LIMIT')
        if process.stdin is None or process.stdout is None:
            raise ValueError('SSH_EXCHANGE_PIPES_REQUIRED')
        checkpoint()
        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)
        pending, output, eof, sent_eof = memoryview(payload), bytearray(), False, False
        while True:
            checkpoint()
            progressed = False
            if not eof:
                try:
                    chunk = os.read(process.stdout.fileno(), min(65536, max_output + 1 - len(output)))
                except BlockingIOError:
                    pass
                else:
                    progressed = bool(chunk)
                    eof = not chunk
                    output.extend(chunk)
                    if len(output) > max_output:
                        raise ValueError('SSH_EXCHANGE_RESPONSE_LIMIT')
            if not sent_eof:
                authorize()
                if pending:
                    try:
                        count = os.write(process.stdin.fileno(), pending[:4096])
                    except BlockingIOError:
                        pass
                    else:
                        pending = pending[count:]
                        progressed = progressed or bool(count)
                else:
                    process.stdin.close()
                    sent_eof = True
                    progressed = True
            code = process.poll()
            if code is not None and code != 0:
                raise subprocess.CalledProcessError(code, 'ssh')
            if sent_eof and eof and code == 0:
                checkpoint()
                return bytes(output)
            if not progressed:
                delay = min(.01, max(0, deadline - time.monotonic()))
                if cancelled is None:
                    time.sleep(delay)
                else:
                    cancelled.wait(delay)
    finally:
        close_process(process)


def close_process(process):
    """Close the owned pipes and confirm the direct SSH process has exited."""
    try:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired as error:
            raise SSHExchangeCleanupError('SSH_EXCHANGE_REAP_UNCONFIRMED') from error
    finally:
        if process.stdin is not None:
            process.stdin.close()
        if process.stdout is not None:
            process.stdout.close()
