"""Operator-only bounded Go acceptance. Never invoked by tests or application startup.

Requires an explicit current account-setting attestation and a fresh, fixed evidence
path. Existing campaigns are inspection-only; this script never resets authority.
Only the credential callback reads OPENCODE_GO, immediately before authorized HTTP.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import time
from uuid import uuid4

from agno.models.message import Message
from fastapi.testclient import TestClient

from agent_factory.config import Settings
from agent_factory.go_development import (CAPABILITY, CONNECTION_NAME, REGISTRATION_REF,
    GoDevelopmentHandle, application_definition, publish_go_development_models, trusted_model_binding)
from agent_factory.go_live import GoLiveCampaign, MODELS
from agent_factory.go_diagnostics import safe_diagnostic
from agent_factory.main import create_app
from agent_factory.opencode_go import GoDevelopmentModel
from agent_factory.usage_ledger import UsagePolicy

PUBLIC_CODE = "def add(a, b): return a + b"


def require(value):
    if not value:
        raise RuntimeError("ACCEPTANCE_FAILED")


def credential():
    return os.environ.get("OPENCODE_GO", "")


def run(args):
    root = Path(args.evidence_directory).absolute()
    path = root / "campaign.sqlite"
    if path.exists():
        # Reinvocation can inspect, but cannot silently create a new budget.
        return {"execution": "inspection-only", "campaign": GoLiveCampaign(path).inspect()}
    require(args.execute_authorized_live and args.use_balance_off and args.auto_reload_off)
    require(getattr(args, "exact_model_sequence", None) == ",".join(MODELS))
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    campaign = GoLiveCampaign.create(path, campaign_id=args.campaign_id, owner_id="alice",
        confirmation_id=args.confirmation_id, use_balance_disabled=True,
        auto_reload_disabled=True, expires_at=time.time() + 3600)
    evidence = {"execution": "live", "accountSettings": "user-attested-off",
                "invoiceVerified": False, "models": [], "campaign": None}
    def persistence_failure(operation, error):
        evidence.setdefault("diagnosticPersistence", []).append({
            "operation": operation, "status": "failed",
            "diagnostic": safe_diagnostic("RUNNER_FAILED", error=error)})

    def stop_safely(code):
        try:
            campaign.stop(code)
        except BaseException as error:
            persistence_failure("campaign-stop", error)

    def record_safely(stage, error=None):
        try:
            require(campaign.journal is not None)
            campaign.journal.record("runner", stage, error=error)
        except BaseException as failure:
            persistence_failure(stage, failure)

    phase = "setup"
    active_task = None
    store = None
    try:
        require(campaign.journal is not None)
        campaign.journal.record("runner", "RUNNER_STARTED")
        with ExitStack() as stack:
            handle = GoDevelopmentHandle(mode="subscription", credential=credential,
                wire_stream=True, native_retries=0, live_campaign=campaign)
            settings = Settings(db_url=args.database_url, workspace=root / "factory",
                development_profile="opencode-go", development_live_validation=True,
                max_workers=1, max_tool_calls=1, temporary_policy="read-only-auto",
                policy_revision="go-live-policy-v1", material_policy_revision="go-live-material-v1",
                runtime_tool_contract="registered-runtime-v1",
                usage_policy=UsagePolicy(revision="go-live-nominal-v1", task_amount_micros=1_000_000,
                    user_amount_micros=10_000_000, task_token_limit=500_000, user_token_limit=2_000_000),
                trusted_connections={REGISTRATION_REF: trusted_model_binding("alice", handle)})
            application = create_app(settings)
            state = application.app.state.factory
            store = state["store"]
            stack.callback(store.engine.dispose)
            stack.callback(store.native_db.db_engine.dispose)
            client = stack.enter_context(TestClient(application))

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
            for model in MODELS:
                phase = model + ":smoke"
                session = "smoke-" + str(uuid4())
                campaign.authorize(session, model, purpose="smoke", owner_id="alice")
                adapter = GoDevelopmentModel(model_id=model, session_id=session, credential=credential,
                    live_campaign=campaign, wire_stream=True, native_retries=0, timeout_seconds=60,
                    max_output_tokens=256)
                result = asyncio.run(adapter.ainvoke([Message(role="user", content=
                    "Coding development smoke test. Return only this Python function, without explanation: " + PUBLIC_CODE)]))
                require(isinstance(result.content, str) and "def add" in result.content)
                phase = model + ":product"
                proposal = post("/api/factory/compositions/proposals", {
                    "goal": 'Coding development: call checksum exactly once with text "' + PUBLIC_CODE +
                            '". Then report the returned SHA-256. Use no other tools.',
                    "mode": model, "applicationRef": app_ref,
                    "connectionRefs": {CONNECTION_NAME: connection["ref"]}, "requestId": str(uuid4())}, 201)
                require(proposal["candidate"]["status"] == "ready")
                plan = post(f"/api/factory/compositions/proposals/{proposal['id']}/accept",
                    {"requestId": str(uuid4())}, 201)
                request_id = str(uuid4())
                task = post("/api/factory/instances", {"planId": plan["id"], "requestId": request_id}, 202)["id"]
                active_task = task
                receipt = client.get("/api/factory/requests/" + request_id)
                require(receipt.status_code == 200 and receipt.json()["taskId"] == task)
                deadline = time.monotonic() + 150
                detail = None
                while time.monotonic() < deadline:
                    response = client.get("/api/factory/jobs/" + task)
                    require(response.status_code == 200)
                    detail = response.json()
                    if detail["job"]["status"] in {"completed", "failed", "unknown", "cancelled"}:
                        break
                    time.sleep(0.2)
                require(detail is not None and detail["job"]["status"] == "completed")
                native_task = store.task(task, "alice")
                ticket = store.native_db.get_job(native_task["run_id"], strict=True)
                require(ticket["max_attempts"] == 1 and ticket["attempt"] == 1)
                usage = store.usage_ledger.inspect("alice", task)
                require([row["state"] for row in usage["attempts"]] == ["SETTLED", "SETTLED"])
                artifact = next(row for row in detail["artifacts"] if row["name"] == "checksum.json")
                download = client.get(f"/api/factory/jobs/{task}/artifacts/{artifact['id']}")
                require(download.status_code == 200)
                digest = hashlib.sha256(download.content).hexdigest()
                require(digest == artifact["sha256"])
                require(hashlib.sha256(PUBLIC_CODE.encode()).hexdigest() in json.dumps(download.json()))
                campaign.complete_model(model, digest)
                evidence["models"].append({"model": model, "taskId": task, "planId": plan["id"],
                    "receiptVerified": True, "artifactSha256": digest, "usage": usage,
                    "status": "completed"})
        phase = "completion-diagnostics"
        campaign.journal.record("runner", "RUNNER_COMPLETED")
    except BaseException as error:
        diagnostic = safe_diagnostic("RUNNER_FAILED", error=error)
        if phase == "completion-diagnostics":
            persistence_failure("RUNNER_COMPLETED", error)
        stop_safely("CANCELLED" if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt)) else "UNKNOWN")
        record_safely("RUNNER_FAILED", error)
        record_safely("RUNNER_STOPPED")
        evidence["diagnostic"] = diagnostic
        evidence["status"] = "stopped"
        evidence["stoppedPhase"] = phase
        if active_task is not None and store is not None:
            try:
                evidence["incompleteTask"] = {"taskId": active_task,
                    "usage": store.usage_ledger.inspect("alice", active_task)}
            except Exception:
                evidence["incompleteTask"] = {"taskId": active_task, "inspection": "unavailable"}
    else:
        evidence["status"] = "completed"
    try:
        evidence["campaign"] = campaign.inspect()
    except BaseException as error:
        persistence_failure("campaign-inspect", error)
        try:
            evidence["campaign"] = campaign.inspect(include_diagnostics=False)
        except BaseException as failure:
            persistence_failure("campaign-facts", failure)
    try:
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    except BaseException as error:
        persistence_failure("evidence-write", error)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-authorized-live", action="store_true")
    parser.add_argument("--use-balance-off", action="store_true")
    parser.add_argument("--auto-reload-off", action="store_true")
    parser.add_argument("--exact-model-sequence", help="New execution requires exactly deepseek-v4-flash,gpt-6-luna; no alias substitution")
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--confirmation-id", required=True)
    parser.add_argument("--evidence-directory", required=True)
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    # Never emit provider/SDK exception strings or incidental console output.
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        try:
            result = run(args)
        except BaseException as error:
            result = {"status": "operator-setup-failed",
                      "diagnostic": safe_diagnostic("RUNNER_FAILED", error=error)}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
