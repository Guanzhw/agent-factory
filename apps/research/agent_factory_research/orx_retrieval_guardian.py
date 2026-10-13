"""Retrieval PID 1: wall/aggregate CPU bounds survive Factory worker death.

Separate from the immutable experiment guardian; a fixed reviewed CLI can wait
on a public endpoint without spending CPU, so CPU-only containment is inadequate.
"""
import os
from pathlib import Path
import sys
import time


def main():
    cpu_limit, wall_limit = float(sys.argv[1]), float(sys.argv[2])
    started = time.monotonic()
    while True:
        try:
            while os.waitpid(-1, getattr(os, "WNOHANG"))[0]:
                pass
        except ChildProcessError:
            pass
        usage = dict(line.split() for line in Path('/sys/fs/cgroup/cpu.stat').read_text().splitlines())
        if int(usage['usage_usec']) >= cpu_limit * 1_000_000 or time.monotonic() - started >= wall_limit:
            os._exit(124)  # Kernel tears down every process in this PID namespace.
        time.sleep(.05)


if __name__ == '__main__':
    main()
