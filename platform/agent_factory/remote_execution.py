"""Presentation and actions for one receiver-owned Factory execution tree.

Trusted connections are installed by the operator. No user URL, token, process
or second native ticket is created by these views. Unavailable receipts retain
the origin reservation and present uncertainty instead of replaying execution.
"""
from __future__ import annotations

import copy
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from .store import canonical, digest


class RemoteExecution:
    def __init__(self, store: Any, client: Any):
        self.store, self.client = store, client

    def placed(self, task: dict) -> bool:
        return bool(self.store.sql("SELECT 1 FROM af_remote_placements WHERE task_id=:id AND owner_id=:owner",
                                   id=task["id"], owner=task["owner_id"]))

    def resolve(self, identifier: str, owner: str) -> tuple[dict, str | None]:
        if "~" not in identifier:
            return self.store.task(identifier, owner), None
        root_id, child_id = identifier.split("~", 1)
        try:
            UUID(root_id); UUID(child_id)
        except ValueError as error:
            raise HTTPException(404, "Scoped remote task not found") from error
        task = self.store.task(root_id, owner)
        if not self.placed(task):
            raise HTTPException(404, "Scoped remote task not found")
        # Receiver validates that child_id belongs to this exact persisted tree.
        return task, child_id

    @staticmethod
    def identifier(origin: dict, remote_id: str, remote_root: str) -> str:
        return origin["id"] if remote_id == remote_root else origin["id"] + "~" + remote_id

    def project(self, task: dict, detail: dict) -> dict:
        value = copy.deepcopy(detail)
        receipt = value.pop("handoff")
        remote_root, remote_id = receipt["remoteTaskId"], value["job"]["id"]
        mapped = self.identifier(task, remote_id, remote_root)
        job = value["job"]
        job.update(id=mapped, ownerId=task["owner_id"], executionPlacement={
            "kind": "remote-factory", "targetRef": self.client._row(task["owner_id"], task["id"])["target_ref"],
            "originTaskId": task["id"], "remoteTaskId": remote_id, "remoteRootTaskId": remote_root,
            "remoteRunId": receipt.get("remoteRunId"), "state": receipt["state"]})
        if remote_id == remote_root:
            job["planId"] = task["plan_id"]
        for event in value.get("events", []):
            event["jobId"] = mapped
        for artifact in value.get("artifacts", []):
            artifact["jobId"] = mapped
        snapshot = value.setdefault("snapshot", {})
        snapshot["remoteHandoff"] = receipt
        snapshot["originEvents"] = self.store.events(task["id"])
        group = snapshot.get("delegation")
        if group:
            for fact in [group["parent"], *group["children"]]:
                if "ownerId" in fact:
                    fact["ownerId"] = task["owner_id"]
                if "owner_id" in fact.get("link", {}):
                    fact["link"]["owner_id"] = task["owner_id"]
                if fact.get("taskId"):
                    fact["taskId"] = self.identifier(task, fact["taskId"], remote_root)
                for key in ("parent_id", "root_id", "child_id"):
                    if fact.get("link", {}).get(key):
                        fact["link"][key] = self.identifier(task, fact["link"][key], remote_root)
        scope = snapshot.get("delegationScope")
        if scope:
            for key in ("parentTaskId", "rootTaskId"):
                scope[key] = self.identifier(task, scope[key], remote_root)
        try:
            self.client.auth.require(task["owner_id"], "run")
        except HTTPException as error:
            if error.status_code != 403:
                raise
            job["allowedActions"] = ["inspect"]
        return value

    def unresolved(self, task: dict, code: int) -> dict:
        plan = self.store.plan(task["plan_id"], task["owner_id"])
        row = self.client._row(task["owner_id"], task["id"])
        job = {"id": task["id"], "ownerId": task["owner_id"], "planId": plan["id"],
               "definitionId": plan["application"], "definitionVersion": 1, "definition": {},
               "binding": {}, "input": {"topic": plan["normalizedGoal"], "mode": plan["mode"], "scenario": "normal"},
               "status": "unknown", "createdAt": task["body"]["createdAt"], "updatedAt": task["body"]["updatedAt"],
               "runtime": "demo" if self.store.settings.demo else "live", "attempt": 0,
               "allowedActions": ["inspect", "reconcile", "cancel"],
               "validationStatus": "远端执行结果尚未确认", "evidenceKind": "未确认",
               "executionPlacement": {"kind": "remote-factory", "targetRef": row["target_ref"],
                                      "originTaskId": task["id"], "state": row["state"]}}
        return {"job": job, "events": self.store.events(task["id"]), "artifacts": [],
                "snapshot": {"remoteUnavailable": True, "remoteReadCode": code, "capacityHeld": not task["terminal"],
                             "syntheticFixture": self.store.settings.demo, "cancelRequested": task["cancel_requested"]}}

    async def detail(self, task: dict, child: str | None = None) -> dict:
        try:
            if child is None:
                placement = self.client._row(task["owner_id"], task["id"])
                if placement["state"] in {"PREPARING", "CANCELLED_NO_DISPATCH"}:
                    receipt = await self.client.receipt(task["owner_id"], task["id"])
                    if receipt["state"] in {"PREPARING", "CANCELLED_NO_DISPATCH"}:
                        pending = self.unresolved(self.store.task(task["id"], task["owner_id"]), 409)
                        cancelled = receipt["state"] == "CANCELLED_NO_DISPATCH"
                        actions = ["inspect", "reconcile"]
                        try:
                            self.client._target(task["owner_id"], placement)
                            if not cancelled:
                                actions += ["cancel", "resume_remote"]
                        except HTTPException as denied:
                            if denied.status_code not in {403, 409, 503}:
                                raise
                        pending["job"].update(status="canceled" if cancelled else "waiting_approval",
                            validationStatus="接收端已确认未开始执行" if cancelled else "接收端管理员审批待完成",
                            allowedActions=actions)
                        pending["snapshot"].update(remoteUnavailable=False, receiverReviewRequired=not cancelled,
                            remoteHandoff=receipt, allStopped=cancelled)
                        return pending
            detail = await self.client.detail(task["owner_id"], task["id"], child)
        except HTTPException as error:
            if child is None and (error.status_code >= 500 or error.status_code in {404, 409}):
                return self.unresolved(task, error.status_code)
            raise
        return self.project(task, detail)

    async def events(self, task: dict, child: str | None = None, *, cursor=None, limit=100) -> dict:
        value = copy.deepcopy(await self.client.events(task["owner_id"], task["id"], child, cursor=cursor, limit=limit))
        receipt = self.client._row(task["owner_id"], task["id"])["body"]["receipt"]
        remote_root = receipt["remoteTaskId"]
        value["receiverPayloadSha256"] = value["payloadSha256"]
        for event in value["events"]:
            event["receiverPayloadSha256"] = event.pop("payloadSha256")
            event["jobId"] = self.identifier(task, event["jobId"], remote_root)
            event["payloadSha256"] = digest({key: item for key, item in event.items() if key != "sequence"})
        value["payloadSha256"] = digest(value["events"])
        value["source"] = "factory-remote-af_events"
        # Cursor/sequence belong to the receiver stream, never the origin table.
        value["executionTargetRef"] = self.client._row(task["owner_id"], task["id"])["target_ref"]
        value["payloadBytes"] = len(canonical(value["events"]).encode())
        if len(canonical(value).encode()) > self.store.event_replay.max_page_bytes:
            raise HTTPException(413, "EVENT_PAGE_LIMIT: projected remote page exceeds its configured byte budget; reduce the page limit")
        return value

    async def instantiate(self, owner: str, plan_id: str, target_ref: str, request_id: str) -> dict:
        row = self.client.reserve(owner, plan_id, target_ref, request_id)
        task = self.store.task(row["task_id"], owner)
        try:
            prepared = await self.client.prepare(owner, task["id"])
            if prepared["state"] != "PREPARING":
                await self.client.dispatch(owner, task["id"])
        except HTTPException as error:
            if error.status_code < 500:
                raise
            # The durable client/receiver boundary records uncertainty. Detail
            # reads recover known work; no second dispatch is issued here.
        return (await self.detail(self.store.task(task["id"], owner)))["job"]

    async def cancel(self, task: dict, child: str | None = None) -> dict:
        try:
            await self.client.cancel(task["owner_id"], task["id"], child)
        except HTTPException as error:
            if child is not None or error.status_code < 500 and error.status_code not in {404, 409}:
                raise
            # The client persists root cancel intent before lookup. Unknown
            # receiver cleanup never means stopped or releases capacity.
        return (await self.detail(self.store.task(task["id"], task["owner_id"]), child))["job"]

    async def action(self, task: dict, action: str, body: dict, child: str | None = None) -> dict:
        await self.client.action(task["owner_id"], task["id"], action, body, child)
        return (await self.detail(self.store.task(task["id"], task["owner_id"]), child))["job"]

    async def delegate(self, task: dict, goal: str, mode: str, request_id: str, child: str | None = None) -> dict:
        result = await self.client.delegate(task["owner_id"], task["id"], goal, mode, request_id, child)
        receipt = await self.client.receipt(task["owner_id"], task["id"])
        remote_id = result["childTask"]["id"]
        detail = await self.detail(task, remote_id)
        result["job"] = detail["job"]
        result["childTask"] = {**result["childTask"], "id": detail["job"]["id"], "owner_id": task["owner_id"]}
        for key in ("parent_id", "root_id", "child_id"):
            if result.get("link", {}).get(key):
                result["link"][key] = self.identifier(task, result["link"][key], receipt["remoteTaskId"])
        return result

    async def children(self, task: dict, child: str | None = None) -> list[dict]:
        rows = await self.client.children(task["owner_id"], task["id"], child)
        receipt = await self.client.receipt(task["owner_id"], task["id"])
        result = copy.deepcopy(rows)
        for row in result:
            # Native child facts include their persisted link and task identity.
            for key in ("taskId", "id", "child_id", "parent_id", "root_id"):
                if row.get(key):
                    row[key] = self.identifier(task, row[key], receipt["remoteTaskId"])
            for key in ("parent_id", "root_id", "child_id"):
                if row.get("link", {}).get(key):
                    row["link"][key] = self.identifier(task, row["link"][key], receipt["remoteTaskId"])
            if row.get("task"):
                row["task"]["id"] = self.identifier(task, row["task"]["id"], receipt["remoteTaskId"])
                row["task"]["owner_id"] = task["owner_id"]
            if "owner_id" in row:
                row["owner_id"] = task["owner_id"]
            if "ownerId" in row:
                row["ownerId"] = task["owner_id"]
            if "owner_id" in row.get("link", {}):
                row["link"]["owner_id"] = task["owner_id"]
        return result
