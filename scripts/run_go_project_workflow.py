"""One native Factory coding roundtrip using an existing Go project policy.

Operator-only. Never creates admission authority or runs a preliminary smoke.
Only the runtime credential callback reads OPENCODE_GO; reports exclude model text.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import time
from uuid import uuid4
from typing import Any

from fastapi.testclient import TestClient

from agent_factory.config import Settings
from agent_factory.go_development import (CAPABILITY, CONNECTION_NAME, REGISTRATION_REF,
    GoDevelopmentHandle, application_definition, publish_go_development_models, trusted_model_binding)
from agent_factory.go_diagnostics import safe_diagnostic
from agent_factory.main import create_app
from agent_factory.usage_ledger import UsagePolicy

MODELS = ("deepseek-flash", "gpt-6-luna")
PUBLIC_CODE = "def add(a, b): return a + b"


def require(value):
    if not value:
        raise RuntimeError("PROJECT_WORKFLOW_CHECK_FAILED")


def credential():
    return os.environ.get("OPENCODE_GO", "")


def safe_usage(usage):
    """Select bounded numeric accounting facts, never ledger/provider free text."""
    states = {"RESERVED", "INFLIGHT", "SETTLED", "UNKNOWN", "RELEASED"}
    attempts = [{"state": row["state"] if row.get("state") in states else "UNKNOWN"}
                for row in usage.get("attempts", [])]
    scopes = []
    for row in usage.get("scopes", []):
        if row.get("scope") != "task":
            continue
        item: dict[str, Any] = {"scope": "task"}
        for key in ("settledTokens", "heldTokens"):
            value = row.get(key)
            if type(value) is int and value >= 0:
                item[key] = value
        scopes.append(item)
    return {"attempts": attempts, "scopes": scopes,
            **({"pricingBasis": "operator-nominal-not-invoice", "invoiceVerified": False,
                "actualCostStatus": "UNKNOWN"} if usage.get("pricingBasis") == "operator-nominal-not-invoice" else {})}


def check_smoke(proof, model):
    """Historical imports cannot establish a current project smoke success."""
    require(proof.get("ownerId") == "alice")
    require(any(row.get("model") == model and row.get("purpose") == "smoke"
                and row.get("state") == "SETTLED" and row.get("actual_model") == model
                and row.get("error_code") is None and type(row.get("ordinal")) is int
                and row["ordinal"] > proof.get("projectPolicy", {}).get("historicalCount", float("inf"))
                for row in proof.get("tickets", [])))


def execute_product(campaign, args):
    evidence = {"model": args.model, "status": "stopped"}
    with ExitStack() as stack:
        handle = GoDevelopmentHandle(mode="subscription", credential=credential,
            wire_stream=True, native_retries=0, live_campaign=campaign)
        settings = Settings(db_url=args.database_url, workspace=Path(args.evidence_directory) / "factory",
            development_profile="opencode-go", development_live_validation=True,
            max_workers=1, max_tool_calls=1, temporary_policy="read-only-auto",
            policy_revision="go-project-policy-v1", material_policy_revision="go-project-material-v1",
            runtime_tool_contract="registered-runtime-v1",
            usage_policy=UsagePolicy(revision="go-project-nominal-v1", task_amount_micros=1_000_000,
                user_amount_micros=10_000_000, task_token_limit=500_000, user_token_limit=2_000_000),
            trusted_connections={REGISTRATION_REF: trusted_model_binding("alice", handle)})
        application = create_app(settings)
        state = application.app.state.factory
        store = state["store"]
        stack.callback(store.engine.dispose)
        stack.callback(store.native_db.db_engine.dispose)
        client = stack.enter_context(TestClient(application))  # type: ignore[arg-type]

        def post(url, body, status):
            response = client.post(url, json=body)
            require(response.status_code == status)
            return response.json()

        def login(owner):
            client.cookies.clear()
            post("/api/factory/demo/login", {"persona": owner}, 200)

        auth = state["auth"]
        auth.authorization.unassign("bob", "factory-user")
        auth.authorization.assign("bob", "factory-manager")
        models = publish_go_development_models(state, author="manager", reviewer="bob")
        seeds = store.materials(published_only=True)
        definition = application_definition(models,
            next(row for row in seeds if row["kind"] == "tool" and row["content"] == "checksum"),
            next(row for row in seeds if row["id"] == "local-environment"))
        for mode in definition["modes"].values():
            mode["budget"]["toolCalls"] = 1
        login("bob")
        app = post("/api/factory/applications/drafts", {"definition": definition, "requestId": str(uuid4())}, 201)
        review = post(f"/api/factory/applications/{app['id']}/versions/{app['version']}/review",
            {"requestId": str(uuid4())}, 201)
        login("manager")
        post(f"/api/factory/applications/reviews/{review['id']}/decision",
             {"approved": True, "requestId": str(uuid4())}, 200)
        app_ref = {key: app[key] for key in ("id", "version", "sha256")}
        connection = state["connections"].bind("alice", REGISTRATION_REF, str(uuid4()), capabilities=[CAPABILITY])
        login("alice")
        proposal = post("/api/factory/compositions/proposals", {
            "goal": 'Coding development: call checksum exactly once with text "' + PUBLIC_CODE +
                    '". Then report the returned SHA-256. Use no other tools.',
            "mode": args.model, "applicationRef": app_ref,
            "connectionRefs": {CONNECTION_NAME: connection["ref"]}, "requestId": str(uuid4())}, 201)
        require(proposal["candidate"]["status"] == "ready")
        plan = post(f"/api/factory/compositions/proposals/{proposal['id']}/accept", {"requestId": str(uuid4())}, 201)
        request_id = str(uuid4())
        task = post("/api/factory/instances", {"planId": plan["id"], "requestId": request_id}, 202)["id"]
        evidence.update(taskId=task, planId=plan["id"], requestId=request_id)
        try:
            receipt = client.get("/api/factory/requests/" + request_id)
            require(receipt.status_code == 200 and receipt.json()["taskId"] == task)
            evidence["receiptVerified"] = True
            deadline = time.monotonic() + 150
            detail = None
            while time.monotonic() < deadline:
                response = client.get("/api/factory/jobs/" + task)
                require(response.status_code == 200)
                detail = response.json()
                if detail["job"]["status"] in {"completed", "failed", "unknown", "cancelled"}:
                    break
                time.sleep(0.2)
            if detail is None or detail["job"]["status"] != "completed":
                raise RuntimeError("PROJECT_WORKFLOW_CHECK_FAILED")
            native_task = store.task(task, "alice")
            ticket = store.native_db.get_job(native_task["run_id"], strict=True)
            require(ticket["max_attempts"] == 1 and ticket["attempt"] == 1)
            usage = store.usage_ledger.inspect("alice", task)
            evidence["usage"] = safe_usage(usage)
            require([row["state"] for row in usage["attempts"]] == ["SETTLED", "SETTLED"])
            require(any(row.get("scope") == "task" and row.get("heldTokens") == 0 for row in usage["scopes"]))
            artifact = next(row for row in detail["artifacts"] if row["name"] == "checksum.json")
            download = client.get(f"/api/factory/jobs/{task}/artifacts/{artifact['id']}")
            require(download.status_code == 200)
            digest = hashlib.sha256(download.content).hexdigest()
            require(digest == artifact["sha256"])
            require(hashlib.sha256(PUBLIC_CODE.encode()).hexdigest() in json.dumps(download.json()))
            evidence.update(status="completed", artifactSha256=digest, nativeAttempts=1)
        except BaseException as error:
            evidence["diagnostic"] = safe_diagnostic("RUNNER_FAILED", error=error)
            # Use the existing scoped cancellation API before shutting down workers.
            try:
                cancel = client.post(f"/api/factory/jobs/{task}/cancel", json={"commandId": str(uuid4())})
                evidence["cancellationRequested"] = 200 <= cancel.status_code < 300
            except BaseException:
                evidence["cancellationRequested"] = False
            try:
                evidence["usage"] = safe_usage(store.usage_ledger.inspect("alice", task))
            except BaseException:
                evidence["usageInspection"] = "unavailable"
    return evidence


def run(args):
    require(args.model in MODELS)
    root = Path(args.evidence_directory).absolute()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    marker = root / "workflow-started.json"
    if marker.exists():
        return {"status": "inspection-only", "model": args.model}
    require(not any(root.iterdir()))
    # Lazy import permits offline contract tests without installing authority.
    from agent_factory.go_project_campaign import GoProjectCampaign
    campaign = GoProjectCampaign(args.campaign)
    campaign.preflight(args.model, "alice")
    check_smoke(campaign.inspect(include_diagnostics=False), args.model)
    descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump({"model": args.model, "requestId": str(uuid4())}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        evidence = execute_product(campaign, args)
    except BaseException as error:
        evidence = {"model": args.model, "status": "stopped", "diagnostic": safe_diagnostic("RUNNER_FAILED", error=error)}
    descriptor = os.open(root / "workflow-result.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(evidence, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--model", choices=MODELS, required=True)
    parser.add_argument("--evidence-directory", required=True)
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        try:
            result = run(args)
        except BaseException as error:
            result = {"status": "stopped", "diagnostic": safe_diagnostic("RUNNER_FAILED", error=error)}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
