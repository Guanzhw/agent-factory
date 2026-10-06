"""Linux cooperative-process limits; not a hostile-code or network sandbox.

CPU/address-space/file-size limits apply to each process, not aggregate usage.
A detached guardian enforces wall time for the retained process group. Trusted
programs must not escape that group, change custody files, or spawn unbounded
children. Missing receipts retain UNKNOWN custody rather than replaying work.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
import hashlib
import inspect
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
import time
from uuid import uuid4
from typing import cast


class ProcessEnforcementError(RuntimeError):
    pass


def _deny():
    raise ProcessEnforcementError("PROCESS_CONTRACT_INVALID")


@dataclass(frozen=True)
class ProcessLimits:
    cpu_seconds: int = 1
    address_space_mb: int = 128
    file_size_bytes: int = 65536
    wall_seconds: float = 3.0

    def __post_init__(self):
        for value, low, high in ((self.cpu_seconds, 1, 2), (self.address_space_mb, 32, 128),
                                 (self.file_size_bytes, 1024, 65536)):
            if type(value) is not int or not low <= value <= high:
                _deny()
        if type(self.wall_seconds) not in {int, float} or not .1 <= self.wall_seconds <= 5:
            _deny()


@dataclass(frozen=True)
class ProcessSpec:
    executable: str
    sha256: str
    argv: tuple[str, ...]

    def __post_init__(self):
        if (type(self.executable) is not str or not Path(self.executable).is_absolute()
                or type(self.sha256) is not str or not re.fullmatch(r"[a-f0-9]{64}", self.sha256)
                or type(self.argv) is not tuple or len(self.argv) > 32
                or any(type(value) is not str or "\x00" in value for value in self.argv)
                or len(json.dumps(self.argv).encode()) > 8192):
            _deny()


@dataclass(frozen=True)
class ResearchProcessLimits:
    """Explicit operator research profile; ordinary ProcessLimits stay unchanged."""
    cpu_seconds: int = 3600
    address_space_mb: int = 65536
    file_size_bytes: int = 2 * 1024**3
    wall_seconds: float = 900.0
    disk_bytes: int = 5 * 1024**3
    output_bytes: int = 16 * 1024**2

    def __post_init__(self):
        bounds = ((self.cpu_seconds, 1, 86400), (self.address_space_mb, 32, 1048576),
                  (self.file_size_bytes, 1024, 2 * 1024**3),
                  (self.disk_bytes, 2 * self.file_size_bytes, 8 * 1024**4),
                  (self.output_bytes, 1024, min(64 * 1024**2, self.file_size_bytes)))
        if any(type(value) is not int or not low <= value <= high for value, low, high in bounds):
            _deny()
        if type(self.wall_seconds) not in {int, float} or not .1 <= self.wall_seconds <= 86400:
            _deny()


@dataclass(frozen=True)
class ResearchProcessSpec(ProcessSpec):
    working_directory: str = ""
    environment: tuple[tuple[str, str], ...] = ()
    working_directory_identity: tuple[int, int] = (0, 0)

    def __post_init__(self):
        super().__post_init__()
        allowed = {"HOME", "PATH", "CUDA_VISIBLE_DEVICES", "TORCHINDUCTOR_CACHE_DIR", "TRITON_CACHE_DIR",
                   "CUDA_CACHE_PATH", "TMPDIR", "HF_HOME", "HF_HUB_OFFLINE", "HF_DATASETS_OFFLINE", "TRANSFORMERS_OFFLINE", "PYTHONNOUSERSITE", "PYTHONPYCACHEPREFIX"}
        if (type(self.working_directory) is not str or not Path(self.working_directory).is_absolute()
                or "\x00" in self.working_directory or type(self.environment) is not tuple
                or len(self.environment) > len(allowed)):
            _deny()
        if (type(self.working_directory_identity) is not tuple or len(self.working_directory_identity) != 2
                or any(type(v) is not int or v <= 0 for v in self.working_directory_identity)):
            _deny()
        names = set()
        for pair in self.environment:
            if (type(pair) is not tuple or len(pair) != 2 or pair[0] not in allowed or pair[0] in names
                    or type(pair[1]) is not str or not 0 < len(pair[1]) <= 4096 or "\x00" in pair[1]):
                _deny()
            names.add(pair[0])
        values = dict(self.environment)
        if any(values.get(key) != "1" for key in ("HF_HUB_OFFLINE", "HF_DATASETS_OFFLINE", "TRANSFORMERS_OFFLINE", "PYTHONNOUSERSITE")):
            _deny()


def open_working_directory(path, expected):
    """Open every component without following links and retain the pinned inode."""
    value = Path(path)
    if not value.is_absolute() or ".." in value.parts:
        raise ValueError("PROCESS_WORKING_DIRECTORY_INVALID")
    flags = (getattr(os, "O_DIRECTORY", None), getattr(os, "O_NOFOLLOW", None))
    if os.name != "posix" or any(type(flag) is not int or flag <= 0 for flag in flags):
        raise ValueError("PROCESS_WORKING_DIRECTORY_UNAVAILABLE")
    directory_flag, nofollow_flag = cast(tuple[int, int], flags)
    fd = os.open("/", os.O_RDONLY | directory_flag | nofollow_flag)
    try:
        for part in value.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | directory_flag | nofollow_flag, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        info = os.fstat(fd)
        if ([info.st_dev, info.st_ino] != list(expected)
                or info.st_uid != getattr(os, "getuid")() or stat.S_IMODE(info.st_mode) & 0o077):
            raise ValueError("PROCESS_WORKING_DIRECTORY_INVALID")
        return fd
    except BaseException:
        os.close(fd)
        raise


def boot_id():
    value = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if not re.fullmatch(r"[a-f0-9-]{36}", value):
        _deny()
    return value


def same_birth(actual, expected):
    def valid(value):
        return (type(value) is dict and type(value.get("bootId")) is str
                and re.fullmatch(r"[a-f0-9-]{36}", value["bootId"]) is not None
                and type(value.get("start")) is str and value["start"].isdigit()
                and all(type(value.get(key)) is int and value[key] > 0 for key in ("pid", "group")))
    return (valid(actual) and valid(expected)
            and all(actual[key] == expected[key] for key in ("bootId", "pid", "start", "group")))


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _root_pin(path):
    directory, file = path.parent.lstat(), path.lstat()
    if (not stat.S_ISDIR(directory.st_mode) or stat.S_IMODE(directory.st_mode) & 0o077
            or not stat.S_ISREG(file.st_mode) or file.st_nlink != 1
            or stat.S_IMODE(file.st_mode) != 0o600):
        _deny()
    return {"directoryDevice": directory.st_dev, "directoryInode": directory.st_ino,
            "fileDevice": file.st_dev, "fileInode": file.st_ino, "path": str(path.absolute())}


def _identity(body):
    result = {key: body[key] for key in ("schema", "id", "ownerId", "taskId", "requestId", "spec", "limits",
                                      "bootId", "rootPin", "specSha256")}
    if "aggregateConfig" in body:
        result.update({key: body[key] for key in ("aggregateConfig", "aggregateBinding", "aggregateIdentity")})
    return result


def spec_contract(spec, limits, aggregate_config=None):
    return {"spec": spec, "limits": limits, **({"aggregateConfig": aggregate_config} if aggregate_config is not None else {})}


def aggregate_backend(body):
    try:
        from .delegated_cgroup import DelegatedCgroupBackend, DelegatedCgroupConfig
    except ImportError:
        from delegated_cgroup import DelegatedCgroupBackend, DelegatedCgroupConfig  # pyright: ignore[reportMissingImports]
    return DelegatedCgroupBackend(DelegatedCgroupConfig.from_dict(body["aggregateConfig"]))


def aggregate_projection(body):
    try:
        from .aggregate_process import project_aggregate_evidence
    except ImportError:
        from aggregate_process import project_aggregate_evidence  # pyright: ignore[reportMissingImports]
    ticket = body["aggregateTicket"]
    proof = {} if ticket["state"] == "NEW" else aggregate_backend(body).inspect(ticket)
    return project_aggregate_evidence(ticket, proof)



def stop_receipt(body, kind, exit_code=None):
    return {"kind": kind, "journalId": body["id"], "identitySha256": body["identitySha256"],
            "bootId": body["bootId"], "guardian": body["guardian"], "child": body["child"],
            "exitCode": exit_code, "groupStopped": True,
            **({"aggregateEvidence": body.get("aggregateStopEvidence")} if kind == "original-delegated-cgroup-released" else {})}


def valid_stop(body):
    receipt = body.get("stopReceipt")
    if body["bootId"] != boot_id() or type(receipt) is not dict:
        return False
    if receipt.get("kind") == "never-dispatched":
        return (("aggregateTicket" not in body or aggregate_projection(body)["state"] == "NEW") and body["state"] == "CANCELLED" and body["guardian"] is None and body["child"] is None
                and receipt == stop_receipt(body, "never-dispatched"))
    if "aggregateConfig" in body:
        try:
            try:
                from .aggregate_process import aggregate_stopped
            except ImportError:
                from aggregate_process import aggregate_stopped  # pyright: ignore[reportMissingImports]
            evidence = aggregate_projection(body)
            return (body["state"] in {"COMPLETED", "CANCELLED", "LIMIT_STOPPED", "FAILED"}
                    and aggregate_stopped(evidence) and evidence == body.get("aggregateStopEvidence")
                    and receipt == stop_receipt(body, "original-delegated-cgroup-released", body.get("exitCode")))
        except Exception:
            return False
    child, guardian = body.get("child"), body.get("guardian")
    return (body["state"] in {"COMPLETED", "CANCELLED", "LIMIT_STOPPED", "FAILED"}
            and same_birth(child, child) and same_birth(guardian, guardian)
            and child.get("group") == child.get("pid")
            and child.get("bootId") == body["bootId"] and guardian.get("bootId") == body["bootId"]
            and receipt == stop_receipt(body, "original-group-stopped", body.get("exitCode")))


def birth(pid):
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
        fields = raw[raw.rfind(")") + 2:].split()
        return {"bootId": boot_id(), "pid": pid, "start": fields[19], "state": fields[0], "group": int(fields[2])}
    except (OSError, ValueError, IndexError):
        return None


def guardian_absent(guardian):
    """Positive absence only; unreadable or malformed proc state keeps custody."""
    if guardian is None:
        return True
    if not same_birth(guardian, guardian):
        return False
    try:
        raw = Path(f"/proc/{guardian['pid']}/stat").read_text()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    try:
        if not raw.startswith(str(guardian["pid"]) + " (") or ") " not in raw:
            return False
        fields = raw[raw.rfind(")") + 2:].split()
        if fields[0] not in {"R", "S", "D", "Z", "T", "t", "X", "x", "K", "W", "P", "I"}:
            return False
        actual = {"bootId": boot_id(), "pid": guardian["pid"], "start": fields[19],
                  "state": fields[0], "group": int(fields[2])}
        if not same_birth(actual, actual):
            return False
        # A group change alone is not proof that the original process died.
        return any(actual[key] != guardian[key] for key in ("bootId", "pid", "start")) or actual["state"] == "Z"
    except (OSError, ValueError, IndexError):
        return False


@contextmanager
def _open_journal(path):
    observed = path.lstat()
    if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1 or stat.S_IMODE(observed.st_mode) != 0o600:
        _deny()
    conn = sqlite3.connect(path, timeout=5)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _read(conn):
    body = json.loads(conn.execute("SELECT body FROM custody WHERE singleton=1").fetchone()[0])
    path = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    if (body.get("identitySha256") != _digest(_identity(body)) or body.get("rootPin") != _root_pin(path)
            or body.get("specSha256") != _digest(spec_contract(body["spec"], body["limits"], body.get("aggregateConfig")))):
        _deny()
    if "aggregateConfig" in body:
        ticket = body.get("aggregateTicket", {})
        if ({key: ticket.get(key) for key in ("id", "name", "bindingSha256", "configSha256", "rootPin")}
                != body["aggregateIdentity"] or ticket.get("bindingSha256") != _digest(body["aggregateBinding"])):
            _deny()
    return body


def _write(conn, body):
    original = _read(conn)
    if _identity(original) != _identity(body) or body.get("identitySha256") != original["identitySha256"]:
        _deny()
    conn.execute("UPDATE custody SET body=? WHERE singleton=1", (json.dumps(body, sort_keys=True),))


def aggregate_operation(path, operation, child=None, *, recovery=False):
    """One actor, original journal, committed ticket intent before each effect.

    Normal callers are the recorded guardian with its unreaped, gated child.
    Recovery is allowed only after that original guardian is positively absent.
    """
    with _open_journal(path) as conn:
        body = _read(conn)
    backend = aggregate_backend(body)
    expected = body["aggregateTicket"]

    def actor(current):
        guardian = current.get("guardian")
        if recovery:
            if not guardian_absent(guardian):
                _deny()
        elif not same_birth(birth(os.getpid()), guardian):
            _deny()
        if current["bootId"] != boot_id() or current["aggregateTicket"] != expected:
            _deny()
        if operation in {"prepare", "attach_before_exec"} and current["cancelRequested"]:
            _deny()

    def authorize():
        with _open_journal(path) as conn:
            actor(_read(conn))

    def persist(ticket):
        nonlocal expected
        with _open_journal(path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = _read(conn)
            actor(current)
            current["aggregateTicket"] = ticket
            _write(conn, current)
        expected = ticket

    authorize()
    if operation == "prepare":
        return backend.prepare(expected, persist=persist, before_effect=authorize)
    if operation == "attach_before_exec":
        return backend.attach_before_exec(expected, child, persist=persist, before_effect=authorize)
    if operation == "kill":
        return backend.kill(expected, persist=persist, before_effect=authorize)
    if operation == "release":
        return backend.release(expected, persist=persist, before_effect=authorize)
    _deny()


def aggregate_finish(path, *, recovery=False):
    """Whole original cgroup emptiness and removal, never leader-only proof."""
    with _open_journal(path) as conn:
        body = _read(conn)
    backend = aggregate_backend(body)
    proof = backend.inspect(body["aggregateTicket"])
    if proof["releasedProof"]:
        return aggregate_projection(body)
    if proof["populated"] is True:
        aggregate_operation(path, "kill", recovery=recovery)
    deadline = time.monotonic() + 1
    while True:
        with _open_journal(path) as conn:
            body = _read(conn)
        proof = backend.inspect(body["aggregateTicket"])
        if proof["populated"] is False:
            break
        if time.monotonic() >= deadline:
            _deny()
        time.sleep(.02)
    aggregate_operation(path, "release", recovery=recovery)
    with _open_journal(path) as conn:
        return aggregate_projection(_read(conn))


class BoundedProcessAdapter:
    def __init__(self, path):
        self.path = Path(path).absolute()
        self._launch_owner = False
        self._process = None
        with _open_journal(self.path) as conn:
            body = _read(conn)
        if body.get("schema") != 1:
            _deny()

    @classmethod
    def create(cls, path, *, owner_id, task_id, request_id, spec, limits: ProcessLimits | ResearchProcessLimits = ProcessLimits(), aggregate_config=None, aggregate_binding=None):
        if sys.platform != "linux" or not hasattr(os, "fork") or not Path("/proc/self/stat").is_file():
            raise ProcessEnforcementError("PROCESS_ENFORCEMENT_UNAVAILABLE")
        if (type(spec), type(limits)) not in {(ProcessSpec, ProcessLimits), (ResearchProcessSpec, ResearchProcessLimits)}:
            _deny()
        if type(owner_id) is not str or not 1 <= len(owner_id) <= 200 or any(ord(c) < 32 or ord(c) == 127 for c in owner_id):
            _deny()
        for value in (task_id, request_id):
            if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value):
                _deny()
        if type(spec) is ResearchProcessSpec:
            directory_fd = open_working_directory(spec.working_directory, spec.working_directory_identity)
            os.close(directory_fd)
        aggregate_body = {}
        if aggregate_config is not None:
            try:
                from .aggregate_process import aggregate_enforcement
            except ImportError:
                from aggregate_process import aggregate_enforcement  # pyright: ignore[reportMissingImports]
            if (type(aggregate_binding) is not dict or aggregate_binding.get("ownerId") != owner_id
                    or aggregate_binding.get("localTaskId") != task_id or aggregate_binding.get("requestId") != request_id):
                _deny()
            aggregate_body = {"aggregateConfig": aggregate_config.to_dict(), "aggregateBinding": aggregate_binding}
            ticket = aggregate_backend(aggregate_body).new_ticket(aggregate_binding)
            aggregate_body.update(aggregateTicket=ticket,
                aggregateIdentity={key: ticket[key] for key in ("id", "name", "bindingSha256", "configSha256", "rootPin")},
                enforcement=aggregate_enforcement(aggregate_config))
        elif aggregate_binding is not None:
            _deny()
        path = Path(path).absolute()
        # Dedicated trusted task directory; no shared-user workspace backend.
        directory = path.parent.lstat()
        if not stat.S_ISDIR(directory.st_mode) or stat.S_IMODE(directory.st_mode) & 0o077:
            _deny()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        with _open_journal(path) as conn:
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("CREATE TABLE custody(singleton INTEGER PRIMARY KEY CHECK(singleton=1),body TEXT NOT NULL)")
            body = {"schema": 1, "id": str(uuid4()), "ownerId": owner_id, "taskId": task_id,
                "requestId": request_id, "spec": asdict(spec), "limits": asdict(limits),
                "state": "PREPARED", "capacityHeld": True, "cancelRequested": False,
                "guardian": None, "child": None, "stoppedProof": False, "stopReceipt": None,
                "bootId": boot_id(), "rootPin": _root_pin(path),
                "enforcement": {"cpu": "per-process-RLIMIT_CPU", "memory": "per-process-RLIMIT_AS",
                    "fileSize": "per-file-RLIMIT_FSIZE", "wall": "cooperative-process-group-guardian",
                    "aggregateQuota": False, "hostileCodeSandbox": False, "networkIsolation": False}}
            body.update(aggregate_body)
            body["specSha256"] = _digest(spec_contract(body["spec"], body["limits"], body.get("aggregateConfig")))
            body["identitySha256"] = _digest(_identity(body))
            conn.execute("INSERT INTO custody VALUES(1,?)", (json.dumps(body, sort_keys=True),))
        result = cls(path)
        result._launch_owner = True
        return result

    def launch(self, *, owner_id, before_effect):
        if not self._launch_owner or not callable(before_effect):
            raise ProcessEnforcementError("PROCESS_REPLAY_DENIED")
        with _open_journal(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            body = _read(conn)
            if body["ownerId"] != owner_id or body["state"] != "PREPARED" or body["cancelRequested"] or body["bootId"] != boot_id():
                raise ProcessEnforcementError("PROCESS_DISPATCH_DENIED")
            approval = before_effect()  # Fresh authority after durable admission lock.
            if inspect.isawaitable(approval):
                if inspect.iscoroutine(approval):
                    approval.close()
                raise ProcessEnforcementError("PROCESS_ASYNC_AUTHORITY_DENIED")
            body["state"] = "DISPATCHING"
            _write(conn, body)
        self._launch_owner = False
        try:
            self._process = subprocess.Popen([sys.executable, "-I", str(Path(__file__).with_name("process_enforcement_guardian.py")), str(self.path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True, start_new_session=True, cwd=self.path.parent, env={"LANG": "C.UTF-8"})
        except Exception:
            with _open_journal(self.path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                body = _read(conn)
                body["state"] = "UNKNOWN"
                _write(conn, body)
            raise ProcessEnforcementError("PROCESS_LAUNCH_UNKNOWN") from None
        return self.inspect(owner_id=owner_id)

    def inspect(self, *, owner_id):
        with _open_journal(self.path) as conn:
            body = _read(conn)
        if body["ownerId"] != owner_id:
            raise ProcessEnforcementError("PROCESS_OWNER_DENIED")
        if self._process is not None:
            self._process.poll()  # Reap only this instance's original guardian.
        if "aggregateConfig" in body:
            body = {**body, "aggregateEvidence": aggregate_projection(body)}
        if body["bootId"] != boot_id() or ((body["state"] in {"COMPLETED", "CANCELLED", "LIMIT_STOPPED", "FAILED"}
                or body.get("stoppedProof") or not body.get("capacityHeld", True)) and not valid_stop(body)):
            return {key: value for key, value in {**body, "state": "UNKNOWN", "capacityHeld": True,
                "stoppedProof": False}.items() if key not in {"spec", "aggregateConfig", "aggregateBinding", "aggregateIdentity", "aggregateTicket"}}
        guardian = body["guardian"]
        if body["state"] not in {"PREPARED", "COMPLETED", "CANCELLED", "LIMIT_STOPPED", "FAILED"}:
            actual = birth(guardian["pid"]) if guardian else None
            if guardian and (actual is None or not same_birth(actual, guardian) or actual["state"] == "Z"):
                body = {**body, "state": "UNKNOWN", "capacityHeld": True, "stoppedProof": False}
        return {key: value for key, value in body.items() if key not in {"spec", "aggregateConfig", "aggregateBinding", "aggregateIdentity", "aggregateTicket"}}

    def cancel(self, *, owner_id):
        with _open_journal(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            body = _read(conn)
            if body["ownerId"] != owner_id:
                raise ProcessEnforcementError("PROCESS_OWNER_DENIED")
            body["cancelRequested"] = True
            if body["state"] == "PREPARED":
                body.update(state="CANCELLED", stoppedProof=True, capacityHeld=False)
                body["stopReceipt"] = stop_receipt(body, "never-dispatched")
            _write(conn, body)
        if "aggregateConfig" in body and not body["stoppedProof"]:
            guardian = body.get("guardian")
            if guardian_absent(guardian):
                try:
                    evidence = aggregate_finish(self.path, recovery=True)
                    with _open_journal(self.path) as conn:
                        conn.execute("BEGIN IMMEDIATE")
                        current = _read(conn)
                        current.update(state="CANCELLED", exitCode=None, stoppedProof=True, capacityHeld=False,
                                       aggregateStopEvidence=evidence)
                        current["stopReceipt"] = stop_receipt(current, "original-delegated-cgroup-released")
                        _write(conn, current)
                except Exception:
                    pass
        return self.inspect(owner_id=owner_id)

    def wait(self, *, owner_id, timeout=7):
        if not 0 < timeout <= 10:
            _deny()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.inspect(owner_id=owner_id)
            if value["stoppedProof"]:
                if self._process is not None:
                    self._process.wait(timeout=1)
                return value
            time.sleep(.02)
        return self.inspect(owner_id=owner_id)
