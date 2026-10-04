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
    return {key: body[key] for key in ("schema", "id", "ownerId", "taskId", "requestId", "spec", "limits",
                                      "bootId", "rootPin", "specSha256")}


def stop_receipt(body, kind, exit_code=None):
    return {"kind": kind, "journalId": body["id"], "identitySha256": body["identitySha256"],
            "bootId": body["bootId"], "guardian": body["guardian"], "child": body["child"],
            "exitCode": exit_code, "groupStopped": True}


def valid_stop(body):
    receipt = body.get("stopReceipt")
    if body["bootId"] != boot_id() or type(receipt) is not dict:
        return False
    if receipt.get("kind") == "never-dispatched":
        return (body["state"] == "CANCELLED" and body["guardian"] is None and body["child"] is None
                and receipt == stop_receipt(body, "never-dispatched"))
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
            or body.get("specSha256") != _digest({"spec": body["spec"], "limits": body["limits"]})):
        _deny()
    return body


def _write(conn, body):
    original = _read(conn)
    if _identity(original) != _identity(body) or body.get("identitySha256") != original["identitySha256"]:
        _deny()
    conn.execute("UPDATE custody SET body=? WHERE singleton=1", (json.dumps(body, sort_keys=True),))


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
    def create(cls, path, *, owner_id, task_id, request_id, spec, limits=ProcessLimits()):
        if sys.platform != "linux" or not hasattr(os, "fork") or not Path("/proc/self/stat").is_file():
            raise ProcessEnforcementError("PROCESS_ENFORCEMENT_UNAVAILABLE")
        if type(spec) is not ProcessSpec or type(limits) is not ProcessLimits:
            _deny()
        for value in (owner_id, task_id, request_id):
            if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value):
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
            body["specSha256"] = _digest({"spec": body["spec"], "limits": body["limits"]})
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
        if body["bootId"] != boot_id() or ((body["state"] in {"COMPLETED", "CANCELLED", "LIMIT_STOPPED", "FAILED"}
                or body.get("stoppedProof") or not body.get("capacityHeld", True)) and not valid_stop(body)):
            return {key: value for key, value in {**body, "state": "UNKNOWN", "capacityHeld": True,
                "stoppedProof": False}.items() if key != "spec"}
        guardian = body["guardian"]
        if body["state"] not in {"PREPARED", "COMPLETED", "CANCELLED", "LIMIT_STOPPED", "FAILED"}:
            actual = birth(guardian["pid"]) if guardian else None
            if guardian and (actual is None or not same_birth(actual, guardian) or actual["state"] == "Z"):
                body = {**body, "state": "UNKNOWN", "capacityHeld": True, "stoppedProof": False}
        return {key: value for key, value in body.items() if key != "spec"}

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
