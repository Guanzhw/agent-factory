"""Observation cannot act on a substituted Docker object or marker link."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent_factory.orx_linux import RUNTIME_IMAGE
from agent_factory.storage_runtime import observe_container


@unittest.skipUnless(os.name == "posix", "Requires descriptor-safe local observation")
class StorageRuntimeObservationTests(unittest.TestCase):
    def test_exact_owner_receipt_and_container_binding_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scope = root / "orx-tasks" / hashlib.sha256(b"alice").hexdigest()[:24] / "task"
            scope.mkdir(parents=True)
            marker = scope / "factory-linux-container.json"
            marker.write_text(json.dumps({"containerId": "a" * 64, "specSha256": "b" * 64}))
            value = {"Id": "a" * 64, "Name": "/af-orx-" + hashlib.sha256(b"alice:task").hexdigest()[:32],
                "Config": {"Image": RUNTIME_IMAGE, "Labels": {"agent-factory.orx-spec": "b" * 64}},
                "HostConfig": {"ReadonlyRootfs": True, "NetworkMode": "none"},
                "Mounts": [{"Source": str(scope), "Destination": str(scope)}],
                "SizeRw": 0, "SizeRootFs": 100, "State": {"Running": False}}
            def command(*args, **kwargs):
                self.assertEqual(args[0], ["docker", "--host", "unix:///var/run/docker.sock", "inspect", "--size", "a" * 64])
                return SimpleNamespace(returncode=0, stdout=json.dumps([value]))
            with patch("agent_factory.storage_runtime.subprocess.run", side_effect=command) as invocation:
                result = observe_container(root, "alice", "task")
                self.assertTrue(result["complete"])
                self.assertFalse(result["physicalAllocationAttributed"])
                value["Id"] = "c" * 64
                self.assertFalse(observe_container(root, "alice", "task")["complete"])
                self.assertFalse(observe_container(root, "bob", "task")["complete"])
                marker.unlink()
                marker.symlink_to(root / "unrelated.json")
                self.assertFalse(observe_container(root, "alice", "task")["complete"])
                self.assertEqual(invocation.call_count, 2)
