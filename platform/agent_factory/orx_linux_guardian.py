"""Task container PID 1: reap detached descendants and enforce aggregate CPU.

Used only by the reviewed Linux local toy profile. No network or provider work.
The kernel tears down the PID namespace when this process exits.
"""
import os
from pathlib import Path
import sys
import time


def main():
    limit = float(sys.argv[1])
    idle_since = time.monotonic()
    while True:
        try:
            while os.waitpid(-1, getattr(os, "WNOHANG"))[0]:
                pass
        except ChildProcessError:
            pass
        usage = dict(line.split() for line in Path('/sys/fs/cgroup/cpu.stat').read_text().splitlines())
        if int(usage['usage_usec']) >= limit * 1_000_000:
            os._exit(124)
        others = [path for path in Path('/proc').iterdir() if path.name.isdigit() and int(path.name) != os.getpid()]
        if others:
            idle_since = time.monotonic()
        elif time.monotonic() - idle_since > 30:
            return
        time.sleep(.1)


if __name__ == '__main__':
    main()
