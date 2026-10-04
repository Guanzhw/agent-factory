"""Private Linux guardian for trusted cooperative fixed executable specifications."""
import hashlib
import os
from pathlib import Path
import importlib
import signal
import stat
import sys
import time

sys.path.insert(0, str(Path(__file__).parent))
from process_enforcement import _open_journal, _read, _write, birth  # type: ignore[reportMissingImports]  # noqa: E402


def update(path, **changes):
    with _open_journal(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        body = _read(conn)
        body.update(changes)
        _write(conn, body)
        return body


def members(group):
    result = []
    for path in Path("/proc").iterdir():
        if path.name.isdigit():
            value = birth(int(path.name))
            if value and value["group"] == group and value["state"] != "Z":
                result.append(value)
    return result


CHILD_ID = None


def main(path):
    global CHILD_ID
    if sys.platform != "linux":
        raise RuntimeError("PROCESS_ENFORCEMENT_UNAVAILABLE")
    resource = importlib.import_module("resource")
    with _open_journal(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        body = _read(conn)
        if body["state"] != "DISPATCHING" or body["guardian"] is not None:
            return
        body["guardian"] = birth(os.getpid())
        _write(conn, body)
    spec, limits = body["spec"], body["limits"]
    binary = os.open(spec["executable"], os.O_RDONLY | getattr(os, "O_NOFOLLOW"))
    info = os.fstat(binary)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Executable is not regular")
    with os.fdopen(os.dup(binary), "rb") as reader:
        if hashlib.file_digest(reader, "sha256").hexdigest() != spec["sha256"]:
            raise ValueError("Executable fingerprint changed")
    os.lseek(binary, 0, os.SEEK_SET)
    output = os.open(path.with_suffix(".output"), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW"), 0o600)
    gate_read, gate_write = os.pipe()
    ready_read, ready_write = os.pipe()
    child = getattr(os, "fork")()
    if child == 0:
        try:
            os.close(gate_write)
            os.close(ready_read)
            getattr(os, "setsid")()
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            resource.setrlimit(resource.RLIMIT_CPU, (limits["cpu_seconds"], limits["cpu_seconds"]))
            memory = limits["address_space_mb"] * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
            resource.setrlimit(resource.RLIMIT_FSIZE, (limits["file_size_bytes"], limits["file_size_bytes"]))
            os.dup2(output, 1)
            os.dup2(output, 2)
            os.close(output)
            os.write(ready_write, b"R")
            os.close(ready_write)
            if os.read(gate_read, 1) != b"G":
                os._exit(125)
            os.close(gate_read)
            os.execve(binary, [spec["executable"], *spec["argv"]], {"LANG": "C.UTF-8"})
        except BaseException:
            os._exit(125)
    os.close(binary)
    os.close(output)
    os.close(gate_read)
    os.close(ready_write)
    if os.read(ready_read, 1) != b"R":
        os.waitpid(child, 0)
        raise ValueError("Child failed before executable release")
    os.close(ready_read)
    identity = birth(child)
    if not identity or identity["group"] != child:
        os.close(gate_write)
        os.waitpid(child, 0)
        raise ValueError("Child custody unavailable")
    CHILD_ID = identity
    body = update(path, state="RUNNING", child=identity)
    if body["cancelRequested"]:
        os.close(gate_write)
    else:
        os.write(gate_write, b"G")
        os.close(gate_write)
    started = time.monotonic()
    cause, status = None, None
    while True:
        with _open_journal(path) as conn:
            body = _read(conn)
        if body["cancelRequested"]:
            cause = "CANCELLED"
        elif time.monotonic() - started >= limits["wall_seconds"]:
            cause = "LIMIT_STOPPED"
        # Keep the root unreaped until group cleanup so its birth ID fences
        # killpg even when the trusted executable left group descendants.
        root = birth(child)
        if root is None or root["start"] != identity["start"]:
            raise ValueError("Child custody changed")
        if cause or root["state"] == "Z":
            if members(child):
                getattr(os, "killpg")(child, getattr(signal, "SIGKILL"))
            _, status = os.waitpid(child, 0)
            break
        time.sleep(.02)
    deadline = time.monotonic() + 1
    while members(child) and time.monotonic() < deadline:
        time.sleep(.02)
    if members(child):
        raise ValueError("Group stop unconfirmed")
    code = os.waitstatus_to_exitcode(status)
    state = cause or ("COMPLETED" if code == 0 else "LIMIT_STOPPED" if code in {-getattr(signal, "SIGKILL"), -getattr(signal, "SIGXCPU"), -getattr(signal, "SIGXFSZ")} else "FAILED")
    update(path, state=state, exitCode=code, stoppedProof=True, capacityHeld=False,
        stopEvidence="original-root-reaped-and-no-live-process-group-members")


if __name__ == "__main__":
    journal = Path(sys.argv[1])
    try:
        main(journal)
    except BaseException:
        # An internal guardian error must also stop positively identified owned
        # work. Failed cleanup remains UNKNOWN; never signal a recycled PID.
        if CHILD_ID is not None:
            current = birth(CHILD_ID["pid"])
            if current and current["start"] == CHILD_ID["start"] and current["group"] == CHILD_ID["pid"]:
                try:
                    getattr(os, "killpg")(CHILD_ID["pid"], getattr(signal, "SIGKILL"))
                    os.waitpid(CHILD_ID["pid"], 0)
                except (ProcessLookupError, ChildProcessError):
                    pass
        # No guessed stop or release: failed custody/receipt remains held.
        try:
            update(journal, state="UNKNOWN", stoppedProof=False, capacityHeld=True)
        except BaseException:
            pass
