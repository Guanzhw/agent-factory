"""Process policy for the runnable research server, not the reusable core."""
from contextlib import contextmanager
import os
import time
import threading
from typing import NoReturn


def shutdown_failed(diagnostic: dict) -> NoReturn:
    # A flush, logger or async cleanup could itself block. The durable original
    # operation remains the recovery record; do not rewrite it on process exit.
    os._exit(1)


@contextmanager
def shutdown_guard():
    # The application uses the same existing 35-second budget. A separate
    # thread also enforces it when synchronous cleanup stalls the event loop.
    deadline = time.monotonic() + 35
    timer = threading.Timer(35, shutdown_failed, args=({'reason': 'deadline'},))
    timer.daemon = True
    timer.start()
    try:
        yield deadline
    except BaseException:
        shutdown_failed({'reason': 'shutdown-error'})
    finally:
        timer.cancel()
