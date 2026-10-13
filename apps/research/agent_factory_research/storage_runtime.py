"""Bounded, read-only attribution of an existing task's original Docker object.

Never constructs an adapter, starts a container, walks Docker's data directory,
or treats SizeRootFs as additive physical disk consumption (especially on vfs).
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from .orx_linux import RUNTIME_IMAGE


def observe_container(workspace: Path, owner: str, task_id: str) -> dict:
    result = {"taskId": task_id, "complete": False, "retentionProtected": True}
    if os.name != "posix" or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", task_id):
        return result
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
    root = os.open(workspace.resolve(), flags)
    try:
        for part in ("orx-tasks", hashlib.sha256(owner.encode()).hexdigest()[:24], task_id):
            child = os.open(part, flags, dir_fd=root)
            os.close(root)
            root = child
        marker = os.open("factory-linux-container.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
        with os.fdopen(marker, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 4096:
                return result
            receipt = json.loads(stream.read(4097))
        cid, spec = receipt["containerId"], receipt["specSha256"]
        if not all(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) for value in (cid, spec)):
            return result
        observed = subprocess.run(["docker", "--host", "unix:///var/run/docker.sock", "inspect", "--size", cid],
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/nonexistent"},
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=2)
        if observed.returncode:
            return result
        values = json.loads(observed.stdout)
        if len(values) != 1:
            return result
        value = values[0]
        config, host = value["Config"], value["HostConfig"]
        expected_name = "/af-orx-" + hashlib.sha256((owner + ":" + task_id).encode()).hexdigest()[:32]
        scope = str(workspace.resolve() / "orx-tasks" / hashlib.sha256(owner.encode()).hexdigest()[:24] / task_id)
        if (value["Id"] != cid or value["Name"] != expected_name or config.get("Labels", {}).get("agent-factory.orx-spec") != spec
                or config["Image"] != RUNTIME_IMAGE or not host["ReadonlyRootfs"] or host["NetworkMode"] != "none"
                or not any(mount["Source"] == scope and mount["Destination"] == scope for mount in value["Mounts"])):
            return result
        writable, rootfs = value.get("SizeRw"), value.get("SizeRootFs")
        if any(type(number) is not int or number < 0 for number in (writable, rootfs)):
            return result
        return {**result, "complete": True, "containerId": cid, "writableLayerBytes": writable,
                "rootFilesystemLogicalBytes": rootfs, "running": value["State"]["Running"],
                "physicalAllocationAttributed": False, "stopEvidence": "not inferred from disk observation"}
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        return result
    finally:
        os.close(root)
