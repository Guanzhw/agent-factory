"""Read-only local capability reporting, never provisioning or an isolation grant.

Kernel reference: https://docs.kernel.org/admin-guide/cgroup-v2.html#delegation
Delegation concerns directory/procs/threads/subtree-control authority; writable
ancestor cpu/memory limit files are not required proof of delegation. Namespace,
socket, controller or writable-directory presence cannot verify an implemented
per-task aggregate backend. No runtime daemon is contacted by these functions.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import stat
import sys

BACKEND = "cooperative-process-v1"
SUPPORTED_SCOPES = (
    "per-process-cpu-time", "per-process-address-space", "per-file-size",
    "cooperative-process-group-wall-time",
)
UNSUPPORTED_SCOPES = (
    "aggregate-cpu", "aggregate-memory", "aggregate-pids", "aggregate-io",
    "aggregate-disk", "network-isolation", "hostile-code-isolation",
)
_OBSERVATIONS = (
    "linux", "posixProcessFacilitiesObserved", "rlimitFacilitiesObserved", "procIdentityReadable",
    "cgroupV2Observed", "cgroupReadOnlyMountObserved", "delegatedSubtreeWritableObserved",
    "cpuControllerObserved", "memoryControllerObserved", "pidsControllerObserved",
    "userSystemdBusObserved", "containerSocketAccessObserved",
)


class IsolationCapabilityError(RuntimeError):
    def __init__(self, code):
        # Caller data, host paths, observed limits and exception text stay out.
        self.code = code if code in {"ISOLATION_POLICY_INVALID", "ISOLATION_BACKEND_UNSUPPORTED",
            "ISOLATION_SCOPE_UNSUPPORTED", "ISOLATION_FACILITIES_UNAVAILABLE"} else "ISOLATION_POLICY_INVALID"
        super().__init__(self.code)


def _read(path):
    try:
        with Path(path).open("rb") as stream:
            data = stream.read(262145)
        return data.decode("utf-8") if len(data) <= 262144 else ""
    except (OSError, UnicodeError):
        return ""


def _socket_access(path):
    try:
        return stat.S_ISSOCK(path.stat().st_mode) and os.access(path, os.R_OK | os.W_OK)
    except OSError:
        return False


def _observe():
    observed: dict[str, bool] = dict.fromkeys(_OBSERVATIONS, False)
    observed["linux"] = sys.platform == "linux"
    if not observed["linux"]:
        return observed
    observed["posixProcessFacilitiesObserved"] = all(hasattr(os, name) for name in
        ("fork", "setsid", "killpg", "O_NOFOLLOW", "waitpid", "execve"))
    try:
        resource = importlib.import_module("resource")
        observed["rlimitFacilitiesObserved"] = all(hasattr(resource, name) for name in
            ("setrlimit", "RLIMIT_CPU", "RLIMIT_AS", "RLIMIT_FSIZE", "RLIMIT_CORE"))
    except ImportError:
        pass
    observed["procIdentityReadable"] = bool(_read("/proc/self/stat") and _read("/proc/sys/kernel/random/boot_id"))
    root = Path("/sys/fs/cgroup")
    mounts = _read("/proc/self/mountinfo")
    for line in mounts.splitlines():
        before, separator, after = line.partition(" - ")
        fields = before.split()
        if separator and len(fields) >= 6 and fields[4] == str(root) and after.split()[:1] == ["cgroup2"]:
            observed["cgroupV2Observed"] = True
            observed["cgroupReadOnlyMountObserved"] = "ro" in fields[5].split(",")
    controllers = set(_read(root / "cgroup.controllers").split())
    for name in ("cpu", "memory", "pids"):
        observed[name + "ControllerObserved"] = name in controllers and observed["cgroupV2Observed"]
    observed["delegatedSubtreeWritableObserved"] = (
        observed["cgroupV2Observed"] and not observed["cgroupReadOnlyMountObserved"]
        and os.access(root, os.W_OK | os.X_OK)
        and all(os.access(root / name, os.W_OK) for name in
            ("cgroup.procs", "cgroup.threads", "cgroup.subtree_control")))
    observed["userSystemdBusObserved"] = _socket_access(Path("/run/user") / str(getattr(os, "getuid")()) / "bus")
    observed["containerSocketAccessObserved"] = _socket_access(Path("/var/run/docker.sock"))
    return observed


def isolation_capabilities():
    """Safe finite metadata; observations cannot promote implementation support."""
    raw = _observe()
    observed = {key: raw.get(key) is True for key in _OBSERVATIONS}
    cooperative = all(observed[key] for key in
        ("linux", "posixProcessFacilitiesObserved", "rlimitFacilitiesObserved", "procIdentityReadable"))
    reasons = ["AGGREGATE_BACKEND_NOT_IMPLEMENTED", "TASK_CGROUP_ENFORCEMENT_UNVERIFIED",
        "IO_DISK_NETWORK_ISOLATION_NOT_IMPLEMENTED"]
    if not cooperative:
        reasons.append("COOPERATIVE_PROCESS_FACILITIES_UNAVAILABLE")
    if not observed["cgroupV2Observed"]:
        reasons.append("CGROUP_V2_NOT_OBSERVED")
    if observed["cgroupReadOnlyMountObserved"]:
        reasons.append("CGROUP_MOUNT_READ_ONLY")
    if not observed["delegatedSubtreeWritableObserved"]:
        reasons.append("DELEGATED_SUBTREE_WRITE_AUTHORITY_NOT_OBSERVED")
    if not all(observed[key] for key in ("cpuControllerObserved", "memoryControllerObserved", "pidsControllerObserved")):
        reasons.append("REQUIRED_CONTROLLERS_NOT_OBSERVED")
    if not observed["userSystemdBusObserved"]:
        reasons.append("USER_SYSTEMD_BUS_NOT_OBSERVED")
    if observed["containerSocketAccessObserved"]:
        reasons.append("CONTAINER_DAEMON_ACCESS_IS_NOT_TASK_ISOLATION_PROOF")
    return {"schema": 1, "backend": BACKEND, "observationMode": "read-only-prerequisites",
        "cooperativeRuntimeAvailable": cooperative,
        "supportedScopes": list(SUPPORTED_SCOPES) if cooperative else [],
        "unsupportedScopes": list(UNSUPPORTED_SCOPES),
        "aggregateEnforcementVerified": False, "taskOwnedBackendSupported": False,
        "containerRuntimeEnforcementVerified": False,
        "observations": observed, "prerequisiteReasons": reasons}


def require_isolation(required_scopes, *, backend=BACKEND):
    """Fresh-check operator requirements; unsupported scopes never downgrade.

    This reports implemented scope support, not authorization to launch, change
    host configuration, or create a cgroup/container. Provider authority remains
    a separate mandatory boundary. Caller-supplied capability reports are absent.
    """
    if type(backend) is not str or backend != BACKEND:
        raise IsolationCapabilityError("ISOLATION_BACKEND_UNSUPPORTED")
    if (type(required_scopes) not in {tuple, list, set, frozenset} or len(required_scopes) > 32
            or any(type(scope) is not str for scope in required_scopes)):
        raise IsolationCapabilityError("ISOLATION_POLICY_INVALID")
    if any(scope not in SUPPORTED_SCOPES for scope in required_scopes):
        raise IsolationCapabilityError("ISOLATION_SCOPE_UNSUPPORTED")
    report = isolation_capabilities()
    if not report["cooperativeRuntimeAvailable"]:
        raise IsolationCapabilityError("ISOLATION_FACILITIES_UNAVAILABLE")
    return report
