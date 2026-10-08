"""Stop-only maintenance using real SQLite persistence and synthetic providers."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from typing import Any, Callable, cast

from fastapi import HTTPException

from agent_factory.resource_maintenance import ResourceMaintenance
from agent_factory.resources import PersistentResourceService, RemoteTarget
from agent_factory.store import canonical
from test_resources_contract import DiskStoreFixture  # type: ignore[reportMissingImports]


class Auth:
    def __init__(self):
        self.owner_status: int | None = None
        self.admin_status: int | None = None

    def require(self, owner, permission):
        status = self.admin_status if owner == "operator" and permission == "agent_os:admin" else self.owner_status
        if owner not in {"operator", "alice"}:
            status = 403
        if status:
            raise HTTPException(status, "synthetic-private-auth-detail")


class Provider:
    def __init__(self):
        self.snapshot = {}
        self.calls = []
        self.confirm_cancel = True
        self.confirm_release = True
        self.read_error = False
        self.cancel_error = False
        self.on_read: Callable[[], None] | None = None

    async def allocate(self, lease_id, owner, fingerprint, limits):
        self.snapshot = {"leaseId": lease_id, "ownerId": owner, "fingerprint": fingerprint, "state": "RUNNING"}
        return self.snapshot.copy()

    async def inspect(self, lease_id, owner):
        self.calls.append("inspect")
        await asyncio.sleep(0)
        if self.on_read:
            self.on_read()
        if self.read_error:
            raise RuntimeError("synthetic-private-provider-error")
        return self.snapshot.copy()

    async def cancel(self, lease_id, owner):
        self.calls.append("cancel")
        if self.confirm_cancel:
            self.snapshot["state"] = "CANCEL_CONFIRMED"
        if self.cancel_error:
            raise TimeoutError("synthetic-private-provider-error")
        return {"accepted": True}

    async def reclaim(self, lease_id, owner):
        self.calls.append("reclaim")
        if self.confirm_release:
            self.snapshot.update(state="RECLAIMED", released=True)
        return {"accepted": True}


class ResourceMaintenanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = DiskStoreFixture(Path(self.temp.name) / "maintenance.sqlite")
        self.addCleanup(self.store.engine.dispose)
        self.auth, self.provider = Auth(), Provider()
        self.target = RemoteTarget("fixture", "compute", frozenset({"alice"}), provider=self.provider, synthetic_fixture=True)
        self.resources = PersistentResourceService(self.store, self.auth, {"fixture": self.target})
        task = self.store.add_task()
        self.lease = await self.resources.allocate("alice", "fixture", task, "fixture-request",
            {"cpu": 1, "memoryMb": 128, "diskMb": 128, "seconds": 60})
        self.maintenance = ResourceMaintenance(self.resources)

    def body(self):
        return json.loads(self.store.sql("SELECT body FROM af_leases WHERE id=:id", id=self.lease["id"])[0]["body"])

    def change(self, **updates):
        body = {**self.body(), **updates}
        self.store.sql("UPDATE af_leases SET body=:body,state=:state WHERE id=:id", body=canonical(body), state=body["state"], id=body["id"])

    async def sweep(self):
        result = await self.maintenance.sweep("operator")
        self.assertNotIn("synthetic-private", json.dumps(result))
        return result["outcomes"][0]

    async def test_revoked_owner_cleanup_without_owner_api_authority(self):
        self.auth.owner_status = 403
        with self.assertRaises(HTTPException): self.resources.inspect("alice", self.lease["id"])
        outcome = await self.sweep()
        self.assertEqual(outcome["status"], "reclaimed")
        self.assertEqual(outcome["reason"], "OWNER_REVOKED")
        self.assertFalse(self.body()["capacityHeld"])
        self.assertEqual(self.provider.calls, ["inspect", "cancel", "inspect", "reclaim", "inspect"])
        self.assertEqual((await self.maintenance.sweep("operator"))["scanned"], 0)

    async def test_deadline_and_local_terminal_are_independent_triggers(self):
        self.change(deadlineAt=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())
        self.assertEqual((await self.sweep())["reason"], "DEADLINE_EXPIRED")

    async def test_local_terminal_still_cancels_running_provider(self):
        original = self.store.task
        self.store.task = lambda identifier, owner=None: {**original(identifier, owner), "terminal": True}
        self.assertEqual((await self.sweep())["reason"], "TASK_TERMINAL")
        self.assertIn("cancel", self.provider.calls)

    async def test_local_cancel_request_is_stop_only_trigger_before_terminal(self):
        original = self.store.task
        self.store.task = lambda identifier, owner=None: {**original(identifier, owner), "cancel_requested": True}
        self.assertEqual((await self.sweep())["reason"], "TASK_CANCEL_REQUESTED")
        self.assertEqual(self.provider.calls.count("cancel"), 1)

    async def test_active_lease_and_unavailable_auth_never_dispatch(self):
        self.assertEqual((await self.sweep())["status"], "skipped")
        self.auth.owner_status = 503
        self.change(deadlineAt=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())
        self.assertEqual((await self.sweep())["reason"], "OWNER_AUTH_UNAVAILABLE")
        self.assertEqual(self.provider.calls, [])
        self.assertTrue(self.body()["capacityHeld"])

    async def test_unknown_cancel_not_replayed_and_no_release_without_terminal(self):
        self.auth.owner_status = 403
        self.provider.cancel_error = True
        self.provider.confirm_cancel = False
        self.assertEqual((await self.sweep())["status"], "held")
        self.assertEqual((await self.sweep())["status"], "held")
        self.assertEqual(self.provider.calls.count("cancel"), 1)
        self.assertNotIn("reclaim", self.provider.calls)
        self.assertEqual(self.body()["cancelAck"], "unknown")

    async def test_accepted_cancel_is_not_release_and_not_replayed(self):
        self.auth.owner_status = 403
        self.provider.confirm_cancel = False
        await self.sweep()
        await self.sweep()
        self.assertEqual(self.body()["cancelAck"], "accepted")
        self.assertTrue(self.body()["capacityHeld"])
        self.assertEqual(self.provider.calls.count("cancel"), 1)
        self.assertNotIn("reclaim", self.provider.calls)

    async def test_release_unknown_held_until_positive_read_never_replayed(self):
        self.auth.owner_status = 403
        self.provider.confirm_release = False
        self.assertEqual((await self.sweep())["status"], "held")
        self.assertEqual(self.body()["releaseAck"], "unknown")
        await self.sweep()
        self.assertEqual(self.provider.calls.count("reclaim"), 1)
        self.provider.snapshot.update(state="RECLAIMED", released=True)
        self.assertEqual((await self.sweep())["status"], "reclaimed")
        self.assertEqual(self.provider.calls.count("reclaim"), 1)

    async def test_read_failure_identity_and_release_flag_fail_closed(self):
        self.auth.owner_status = 403
        self.provider.read_error = True
        self.assertEqual((await self.sweep())["reason"], "READ_UNCONFIRMED")
        self.provider.read_error = False
        for update in ({"ownerId": "bob"}, {"fingerprint": "forged"}, {"state": "RECLAIMED"}, {"state": "RECLAIMED", "released": 1}):
            original = self.provider.snapshot.copy()
            self.provider.snapshot.update(update)
            self.assertEqual((await self.sweep())["status"], "held")
            self.provider.snapshot = original
        self.assertNotIn("cancel", self.provider.calls)
        self.assertNotIn("reclaim", self.provider.calls)
        self.assertTrue(self.body()["capacityHeld"])

    async def test_target_rebound_directory_missing_and_body_tamper_hold(self):
        self.auth.owner_status = 403
        self.resources.targets["fixture"] = replace(self.target, configuration_revision="2")
        self.assertEqual((await self.sweep())["reason"], "TARGET_REBOUND")
        self.resources.targets["fixture"] = self.target
        self.change(fingerprint="forged")
        self.assertEqual((await self.sweep())["reason"], "CUSTODY_INVALID")
        self.change(fingerprint=self.lease["fingerprint"])
        self.store.sql("DELETE FROM af_resources")
        self.assertEqual((await self.sweep())["reason"], "DIRECTORY_UNAVAILABLE")
        self.assertEqual(self.provider.calls, [])

    async def test_current_admin_and_target_rechecked_after_read(self):
        self.auth.owner_status = 403
        self.provider.on_read = lambda: setattr(self.auth, "admin_status", 403)
        self.assertEqual((await self.sweep())["reason"], "AUTHORITY_OR_CUSTODY_UNAVAILABLE")
        self.assertEqual(self.provider.calls, ["inspect"])
        self.auth.admin_status = None
        self.provider.on_read = lambda: self.resources.targets.update(fixture=replace(self.target))
        self.assertEqual((await self.sweep())["reason"], "TARGET_UNAVAILABLE")
        self.assertNotIn("cancel", self.provider.calls)

    async def test_admin_revoked_after_cas_preserves_unknown_without_dispatch_or_replay(self):
        self.auth.owner_status = 403
        original = self.resources._claim_effect

        def claim(owner, lease_id, field, state):
            result = original(owner, lease_id, field, state)
            self.auth.admin_status = 403
            return result

        self.resources._claim_effect = claim
        self.assertEqual((await self.sweep())["reason"], "AUTHORITY_OR_CUSTODY_UNAVAILABLE")
        self.assertEqual(self.body()["cancelAck"], "unknown")
        self.assertNotIn("cancel", self.provider.calls)
        self.resources._claim_effect = original
        self.auth.admin_status = None
        self.assertEqual((await self.sweep())["status"], "held")
        self.assertNotIn("cancel", self.provider.calls)

    async def test_two_sweeps_reuse_existing_effect_cas(self):
        self.auth.owner_status = 403
        await asyncio.gather(self.maintenance.sweep("operator"), self.maintenance.sweep("operator"))
        self.assertEqual(self.provider.calls.count("cancel"), 1)
        self.assertEqual(self.provider.calls.count("reclaim"), 1)
        self.assertFalse(self.body()["capacityHeld"])

    async def test_cursor_reaches_expired_lease_beyond_active_first_page(self):
        base = self.body()
        row = self.store.sql("SELECT * FROM af_leases WHERE id=:id", id=base["id"])[0]
        self.store.sql("DELETE FROM af_leases")
        for index in range(21):
            identifier = f"lease-{index:03d}"
            body = {**base, "id": identifier, "requestId": identifier}
            if index == 20:
                body["deadlineAt"] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
                self.provider.snapshot["leaseId"] = identifier
            self.store.sql("INSERT INTO af_leases VALUES(:id,:owner,:target,:request,:fingerprint,:state,:body)",
                id=identifier, owner=row["owner_id"], target=row["target_id"], request=identifier,
                fingerprint=row["fingerprint"], state=row["state"], body=canonical(body))
        first = await self.maintenance.sweep("operator")
        self.assertEqual(first["scanned"], 20)
        self.assertEqual(first["nextCursor"], "lease-019")
        self.assertTrue(all(value["status"] == "skipped" for value in first["outcomes"]))
        self.assertEqual(self.provider.calls, [])
        second = await self.maintenance.sweep("operator", after=first["nextCursor"])
        self.assertEqual(second["scanned"], 1)
        self.assertIsNone(second["nextCursor"])
        self.assertEqual(second["outcomes"][0]["leaseId"], "lease-020")
        self.assertEqual(second["outcomes"][0]["status"], "reclaimed")
        # Explicit reset starts a new bounded scan, not a snapshot or scheduler.
        self.assertEqual((await self.maintenance.sweep("operator"))["scanned"], 20)

    async def test_cursor_validation_rejects_unbounded_nonidentifiers(self):
        for after in (True, 0, [], {}, "", "a"*129, "../lease", "lease' OR 1=1", "lease\n"):
            with self.subTest(after=after), self.assertRaises(HTTPException) as caught:
                await self.maintenance.sweep("operator", after=after)
            self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(self.provider.calls, [])

    async def test_admin_required_limit_bounded_and_compute_only(self):
        self.auth.admin_status = 403
        with self.assertRaises(HTTPException): await self.maintenance.sweep("operator")
        self.auth.admin_status = None
        for limit in (True, 0, 101, "20"):
            with self.assertRaises(HTTPException): await self.maintenance.sweep("operator", limit=cast(Any, limit))
        self.change(axis="runtime")
        self.assertEqual((await self.maintenance.sweep("operator", limit=1))["scanned"], 0)
        self.assertEqual(self.provider.calls, [])


if __name__ == "__main__":
    unittest.main()
