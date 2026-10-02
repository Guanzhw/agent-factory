"""Finite 20-user native-queue workload, not target-host throughput evidence."""
import json
import os
import shutil
from pathlib import Path
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

import test_capacity_postgres as fixture


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires isolated PostgreSQL")
class ResourcePressurePostgresTests(unittest.TestCase):
    setUpClass = classmethod(fixture.CapacityPostgresTests.setUpClass.__func__)
    tearDown = fixture.CapacityPostgresTests.tearDown
    headers = fixture.CapacityPostgresTests.headers
    request = fixture.CapacityPostgresTests.request
    plan = fixture.CapacityPostgresTests.plan
    submit = fixture.CapacityPostgresTests.submit
    wait = fixture.CapacityPostgresTests.wait
    cancel_and_confirm = fixture.CapacityPostgresTests.cancel_and_confirm
    held = fixture.CapacityPostgresTests.held
    tickets = fixture.CapacityPostgresTests.tickets

    def test_bounded_twenty_user_fifo_progress_with_unknown_and_low_water_pressure(self):
        start = time.monotonic()
        samples, admitted, rejected, stopped = [], {}, [], []
        reserve = self.settings.storage_task_reserve_bytes
        def sample(phase):
            held = self.store.sql("SELECT COUNT(*) AS n,COALESCE(SUM(bytes),0) AS bytes FROM af_disk_holds WHERE state='HELD'")[0]
            samples.append({"seconds": round(time.monotonic() - start, 4), "phase": phase,
                "heldTasks": self.held(), "heldDiskBytes": int(held["bytes"]), "heldDiskCount": held["n"],
                "workspaceFreeBytes": shutil.disk_usage(self.workspace.name).free,
                "processCpuSeconds": round(os.times().user + os.times().system, 4),
                "admittedUsers": len(admitted), "stoppedUsers": len(stopped), "rejectedAttempts": len(rejected)})
            status = Path("/proc/self/status")
            if status.is_file():
                rss = next(line for line in status.read_text().splitlines() if line.startswith("VmRSS:"))
                samples[-1]["processRssBytes"] = int(rss.split()[1]) * 1024
            self.assertLessEqual(self.held(), 12)
            self.assertLessEqual(held["n"], 12)
        # One absent native acknowledgement deliberately consumes its own slot
        # and disk reservation throughout the experiment.
        unknown_owner = self.users[0]
        with patch.object(self.state["bridge"], "submit", side_effect=HTTPException(503, "Owned uncertainty fixture")):
            unknown, _ = self.submit(unknown_owner, self.plan(unknown_owner))
        self.assertEqual(unknown["status"], "unknown")
        plans = {owner: self.plan(owner) for owner in self.users}
        requests = {owner: {"planId": plans[owner]["id"], "requestId": str(uuid4())} for owner in self.users}
        # No competing refill is submitted by already served users; this is a
        # finite client workload, not a guarantee of pre-admission fairness.
        pending = list(self.users)
        for wave in range(3):
            current = []
            for owner in list(pending):
                response = self.client.post("/api/factory/instances", headers=self.headers(owner), json=requests[owner])
                self.assertIn(response.status_code, {202, 429}, response.text)
                if response.status_code == 202:
                    task = response.json()["id"]
                    current.append((owner, task))
                    admitted[owner] = {"task": task, "admittedSeconds": round(time.monotonic() - start, 4)}
                    pending.remove(owner)
                    self.assertEqual(self.tickets(task), 1)
                else:
                    rejected.append(owner)
                    self.assertFalse(self.store.sql("SELECT 1 FROM af_tasks WHERE owner_id=:owner AND request_id=:key", owner=owner, key=requests[owner]["requestId"]))
                sample("admission")
            self.assertTrue(current)
            for owner, task in current:
                value = self.wait(owner, task, {"waiting_input", "failed", "unknown"})
                self.assertEqual(value["job"]["status"], "waiting_input", value)
                admitted[owner]["nativeProgressSeconds"] = round(time.monotonic() - start, 4)
                self.assertEqual(self.store.sql("SELECT state FROM af_disk_holds WHERE task_id=:task", task=task)[0]["state"], "HELD")
                sample("waiting_input")
            # Simulated observation changes, never real disk exhaustion. A
            # same-key read is still recoverable under physical pressure.
            owner, task = current[0]
            with patch.object(self.store.storage, "filesystems", return_value=[{"freeBytes": 1}]):
                original = self.client.post("/api/factory/instances", headers=self.headers(owner), json=requests[owner])
                self.assertEqual(original.status_code, 202)
                self.assertEqual(original.json()["id"], task)
                pressure_owner = self.users[-1]
                denied = self.client.post("/api/factory/instances", headers=self.headers(pressure_owner),
                    json={"planId": plans[pressure_owner]["id"], "requestId": str(uuid4())})
                # Existing quota fences can reject before disk observation.
                self.assertIn(denied.status_code, {429, 507})
                sample("low_water")
            for owner, task in current:
                self.cancel_and_confirm(owner, task)
                stopped.append(owner)
                admitted[owner]["stoppedSeconds"] = round(time.monotonic() - start, 4)
                self.assertEqual(self.store.sql("SELECT state FROM af_disk_holds WHERE task_id=:task", task=task)[0]["state"], "RELEASED")
                sample("positive_cleanup")
            if not pending:
                break
        self.assertFalse(pending, "No user in this finite workload may remain starved")
        self.assertEqual(len(admitted), 20)
        self.assertTrue(rejected)
        self.assertEqual(self.held(), 1)
        self.request(unknown_owner, "POST", f'/jobs/{unknown["id"]}/cancel')
        self.assertEqual(self.store.sql("SELECT state FROM af_disk_holds WHERE task_id=:id", id=unknown["id"])[0]["state"], "HELD")
        sample("unknown_preserved")
        fresh_owner = self.users[-1]
        with patch.object(self.store.storage, "filesystems", return_value=[{"freeBytes": 1}]):
            denied = self.client.post("/api/factory/instances", headers=self.headers(fresh_owner),
                json={"planId": plans[fresh_owner]["id"], "requestId": str(uuid4())})
            self.assertEqual(denied.status_code, 507)
        self.assertLess(time.monotonic() - start, 180, "Bounded workload exceeded its measurement window")
        evidence = {"schema": 1, "configuration": {"users": 20, "nativeWorkers": 2, "globalCap": 12,
            "perUserCap": 2, "taskDiskReservationBytes": reserve, "lowWaterBytes": self.settings.storage_low_water_bytes,
            "unknownHeldThroughout": 1, "model": "deterministic synthetic", "pressure": "injected observation; no disk filling"},
            "samples": samples, "users": admitted, "allFiniteWorkloadUsersProgressed": True,
            "preAdmissionFairnessUnderUnboundedRefillProven": False, "targetHostCapacityProven": False}
        for name in ("cpu.max", "memory.max"):
            path = Path("/sys/fs/cgroup") / name
            if path.is_file():
                evidence["configuration"][name] = path.read_text().strip()
        destination = os.getenv("FACTORY_PRESSURE_EVIDENCE")
        if destination:
            Path(destination).write_text(json.dumps(evidence, indent=2) + "\n")
