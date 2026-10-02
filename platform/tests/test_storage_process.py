"""Actual process death after rename on a generated, reconstructible directory."""
import json
import os
import unittest
from uuid import uuid4

import httpx

from agent_factory.config import Settings
from agent_factory.store import Store
from agent_factory.storage_governance import StorageGovernance
import test_control_commands_process as fixture


def owned_directory(test, task):
    store = Store(test.database.url, Settings(db_url=test.database.url, workspace=test.workspace))
    try:
        storage = StorageGovernance(store, None)
        path = storage.directory(task, "process-fixture-only")
        (path / "synthetic.txt").write_bytes(b"Owned recoverable storage fixture")
        return path
    finally:
        store.engine.dispose()


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL") and os.name == "posix", "Requires isolated PostgreSQL and Linux")
class StorageProcessTests(unittest.TestCase):
    setUp = fixture.CommandProcessTests.setUp
    tearDown = fixture.CommandProcessTests.tearDown
    start = fixture.CommandProcessTests.start
    api = fixture.CommandProcessTests.api
    waiting = fixture.CommandProcessTests.waiting

    def test_rename_survives_process_exit_and_read_only_recovery_does_not_repeat_move(self):
        task, _ = self.waiting("answer")
        path = owned_directory(self, task)
        self.api("POST", "/jobs/" + task + "/cancel")
        plan = self.api("POST", "/storage/retention/plans", {"objectId": path.name, "requestId": str(uuid4())})
        endpoint = "/storage/retention/plans/" + plan["id"]
        (self.workspace / "fault.json").write_text(json.dumps({"phase": "storage-before-QUARANTINED", "commandId": plan["id"]}))
        with self.assertRaises(httpx.TransportError):
            self.api("POST", endpoint + "/quarantine")
        self.assertEqual(self.process.wait(10), 88)
        self.assertFalse(path.exists())
        self.start()
        recovered = self.api("GET", endpoint)
        self.assertEqual(recovered["state"], "QUARANTINED")
        self.assertEqual(recovered["reclaimedLogicalBytes"], 0)
        self.assertFalse(path.exists())
        restored = self.api("POST", endpoint + "/restore")
        self.assertEqual(restored["state"], "RESTORED")
        self.assertEqual((path / "synthetic.txt").read_bytes(), b"Owned recoverable storage fixture")
