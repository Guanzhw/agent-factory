"""Fixed installed ASKPASS entry point; stdout belongs exclusively to OpenSSH."""
import math
import os
import sys
import time


def main():
    password = bytearray()
    pipe = controller = None
    try:
        from . import windows_ssh_support as w
        expected = b"Enter passphrase for key 'identity': "
        if len(sys.argv) != 2 or sys.argv[1].encode('utf-8') != expected:
            return 1
        if os.environ.get('SSH_ASKPASS_PROMPT') in ('confirm', 'none'):
            return 1
        deadline = float(os.environ['FACTORY_SSH_DEADLINE'])
        if not math.isfinite(deadline) or time.monotonic() >= deadline:
            return 1
        controller = w.process(int(os.environ['FACTORY_SSH_CONTROLLER']))
        pipe = w.client_pipe(os.environ['FACTORY_SSH_PIPE'])
        if w.pipe_pid(pipe, False) != int(os.environ['FACTORY_SSH_CONTROLLER']) or not w.alive(controller):
            return 1
        w.transfer(pipe, deadline, payload=b'READY')
        password = bytearray(w.transfer(pipe, deadline, size=64))
        if len(password) != 64:
            return 1
        w.transfer(pipe, deadline, payload=b'RECEIVED')
        sys.stdout.buffer.write(password + b'\n')
        sys.stdout.buffer.flush()
        return 0
    except Exception:
        # No exception text or diagnostics may enter the private passphrase channel.
        return 1
    finally:
        password[:] = b'\0' * len(password)
        if pipe is not None:
            pipe.Close()
        if controller is not None:
            controller.Close()
