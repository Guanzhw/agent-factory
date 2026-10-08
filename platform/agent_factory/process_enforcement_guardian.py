"""Private Linux guardian for trusted cooperative fixed executable specifications."""
import sys

# Isolated mode ignores PYTHON* environment variables. Require the explicit
# interpreter flag before importing any local module from the sealed site.
if __name__ == '__main__' and not sys.dont_write_bytecode:
    sys.stderr.write('PROCESS_GUARDIAN_BYTECODE_DENIED\n')
    raise SystemExit(126)

import hashlib
import os
from pathlib import Path
import importlib
import signal
import stat
import time

sys.path.insert(0, str(Path(__file__).parent))
from process_enforcement import _open_journal, _read, _write, birth, boot_id, same_birth, stop_receipt, aggregate_operation, aggregate_finish, aggregate_projection, open_working_directory, interpreter_module, execute_pinned_interpreter  # type: ignore[reportMissingImports]  # noqa: E402


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


def drain_output(pipe, output, count, limit):
    # Bound work per tick even when a writer continuously fills the pipe.
    for _ in range(16):
        try:
            chunk = os.read(pipe, 65536)
        except BlockingIOError:
            return count, False
        if not chunk:
            return count, False
        available = max(0, limit - count)
        kept = memoryview(chunk)[:available]
        while kept:
            written = os.write(output, kept)
            if written <= 0:
                raise OSError("PROCESS_OUTPUT_WRITE_FAILED")
            kept = kept[written:]
        count += len(chunk)
        if count > limit:
            return count, True
    return count, False


CHILD_ID = None


def main(path):
    global CHILD_ID
    if sys.platform != "linux":
        raise RuntimeError("PROCESS_ENFORCEMENT_UNAVAILABLE")
    resource = importlib.import_module("resource")
    with _open_journal(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        body = _read(conn)
        if body["state"] != "DISPATCHING" or body["guardian"] is not None or body["bootId"] != boot_id():
            return
        body["guardian"] = birth(os.getpid())
        _write(conn, body)
    if "aggregateConfig" in body:
        aggregate_operation(path, "prepare")
    spec, limits = body["spec"], body["limits"]
    research = "working_directory" in spec
    directory = open_working_directory(spec["working_directory"], spec["working_directory_identity"]) if research else None
    output_read, output_write = os.pipe() if research else (None, None)
    if output_read is not None:
        os.set_blocking(output_read, False)
    uv_contract = spec.get('interpreter_contract')
    binary = (interpreter_module().open_interpreter(uv_contract, spec['executable'], spec['sha256'])
              if uv_contract is not None else os.open(spec["executable"], os.O_RDONLY | getattr(os, "O_NOFOLLOW")))
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
            child_output = output_write if output_write is not None else output
            if output_read is not None:
                os.close(output_read)
            os.dup2(child_output, 1)
            os.dup2(child_output, 2)
            if output_write is not None:
                os.close(output_write)
            os.close(output)
            os.write(ready_write, b"R")
            os.close(ready_write)
            if os.read(gate_read, 1) != b"G":
                os._exit(125)
            os.close(gate_read)
            # Re-read cancellation and immutable custody after gate delay, just
            # before exec. Caller authority itself is never serialized/replayed.
            with _open_journal(path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                current = _read(conn)
                if (current["cancelRequested"] or current["bootId"] != boot_id()
                        or not same_birth(birth(os.getpid()), current["child"])):
                    os._exit(125)
            environment = {"LANG": "C.UTF-8"}
            if directory is not None:
                checked = open_working_directory(spec["working_directory"], current["spec"]["working_directory_identity"])
                os.close(checked)
                os.fchdir(directory)
                os.close(directory)
                environment.update(dict(spec["environment"]))
            def before_exec():
                # Long bounded inventory reads cannot hide cancellation at the
                # original gate; recheck the unchanged original custody again.
                with _open_journal(path) as conn:
                    current = _read(conn)
                    return (not current['cancelRequested'] and current['bootId'] == boot_id()
                            and same_birth(birth(os.getpid()), current['child']))
            execute_pinned_interpreter(spec, binary, environment, before_exec)
        except BaseException:
            os._exit(125)
    os.close(binary)
    if directory is not None:
        os.close(directory)
    if output_write is not None:
        os.close(output_write)
    else:
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
    body = update(path, state="DISPATCHING", child=identity)
    if "aggregateConfig" in body:
        try:
            aggregate_operation(path, "attach_before_exec", identity)
        except BaseException:
            os.close(gate_write)
            raise
    body = update(path, state="RUNNING")
    if body["cancelRequested"]:
        os.close(gate_write)
    else:
        os.write(gate_write, b"G")
        os.close(gate_write)
    started = time.monotonic()
    cause, status = None, None
    output_count = 0
    while True:
        with _open_journal(path) as conn:
            body = _read(conn)
        if "aggregateConfig" in body and not aggregate_projection(body)["limitsReadbackVerified"]:
            # A witnessed controls mismatch permanently fails this execution;
            # original-group cleanup may still positively release capacity.
            body = update(path, aggregateLimitsDrift=True)
            cause = "FAILED"
        if body.get("aggregateLimitsDrift"):
            cause = "FAILED"
        elif body["cancelRequested"]:
            cause = "CANCELLED"
        elif time.monotonic() - started >= limits["wall_seconds"]:
            cause = "LIMIT_STOPPED"
        if output_read is not None:
            output_count, exceeded = drain_output(output_read, output, output_count, limits["output_bytes"])
            if exceeded and cause is None:
                cause = "LIMIT_STOPPED"
        # Keep the root unreaped until group cleanup so its birth ID fences
        # killpg even when the trusted executable left group descendants.
        root = birth(child)
        if root is None or not same_birth(root, identity):
            raise ValueError("Child custody changed")
        if cause or root["state"] == "Z":
            if "aggregateConfig" in body:
                # Guardian stays outside the group; blocked child membership was
                # confirmed before exec. This also stops setsid descendants.
                aggregate_finish(path)
            elif members(child):
                getattr(os, "killpg")(child, getattr(signal, "SIGKILL"))
            _, status = os.waitpid(child, 0)
            break
        time.sleep(.02)
    deadline = time.monotonic() + 1
    while members(child) and time.monotonic() < deadline:
        time.sleep(.02)
    if members(child):
        raise ValueError("Group stop unconfirmed")
    if output_read is not None:
        output_count, exceeded = drain_output(output_read, output, output_count, limits["output_bytes"])
        if exceeded and cause is None:
            cause = "LIMIT_STOPPED"
        os.close(output_read)
        os.fsync(output)
        os.close(output)
    code = os.waitstatus_to_exitcode(status)
    state = cause or ("COMPLETED" if code == 0 else "LIMIT_STOPPED" if code in {-getattr(signal, "SIGKILL"), -getattr(signal, "SIGXCPU"), -getattr(signal, "SIGXFSZ")} else "FAILED")
    with _open_journal(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        body = _read(conn)
        if not same_birth(body["child"], identity) or not same_birth(body["guardian"], birth(os.getpid())):
            raise ValueError("Stop receipt identity changed")
        if "aggregateConfig" in body:
            body["aggregateStopEvidence"] = aggregate_projection(body)
        body.update(state=state, exitCode=code, stoppedProof=True, capacityHeld=False,
            stopEvidence="original-root-reaped-and-no-live-process-group-members")
        body["stopReceipt"] = stop_receipt(body, "original-delegated-cgroup-released" if "aggregateConfig" in body else "original-group-stopped", code)
        _write(conn, body)


if __name__ == "__main__":
    journal = Path(sys.argv[1])
    try:
        main(journal)
    except BaseException:
        # An internal guardian error must also stop positively identified owned
        # work. Failed cleanup remains UNKNOWN; never signal a recycled PID.
        if CHILD_ID is not None:
            current = birth(CHILD_ID["pid"])
            if current is not None and same_birth(current, CHILD_ID) and current["group"] == CHILD_ID["pid"]:
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
