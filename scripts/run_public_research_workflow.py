"""Operator development acceptance: public retrieval or separately labelled synthesis fixture.

Never loads model credentials. Scientific live provider selection is not implied.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import hashlib
import io
import json
import logging
from pathlib import Path
import time
from uuid import uuid4

from fastapi.testclient import TestClient
from agent_factory.main import create_app

QUESTION = "Development example: describe these public source records and the limits of their short abstract excerpts."


def require(value):
    if not value:
        raise ValueError("PUBLIC_RESEARCH_ACCEPTANCE_FAILED")


def run(args):
    root = Path(args.evidence_directory).absolute()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    with (root / "started.json").open("x") as stream:
        json.dump({"phase": args.phase}, stream)
    evidence = {"phase": args.phase, "ownerId": "alice", "status": "stopped",
                "scientificProviderCalled": False, "scientificEndToEndAccepted": False}
    if args.phase == "retrieval":
        from agent_factory.pubmed_profile import (pubmed_settings, publish_pubmed_application,
            PubMedProvider, REGISTRATION_REF, CONNECTION_NAME, CAPABILITY)
        settings = pubmed_settings(db_url=args.database_url, workspace=root / "factory", provider=PubMedProvider("alice"))
        def publish(state):
            return publish_pubmed_application(state, author="manager", reviewer="bob")
        mode = "bibliography"
    else:
        from agent_factory.literature_synthesis_profile import (synthesis_settings, publish_synthesis_application,
            REGISTRATION_REF, CONNECTION_NAME)
        from agent_factory.literature_synthesis import SCIENTIFIC_CAPABILITY as CAPABILITY
        require(args.source_evidence is not None)
        with Path(args.source_evidence).open("rb") as stream:
            raw = stream.read(131073)
        require(len(raw) <= 131072)
        previous = json.loads(raw)
        require(previous["phase"] == "retrieval" and previous["ownerId"] == "alice" and previous["status"] == "completed")
        projection = previous["literatureEvidence"]
        settings = synthesis_settings(db_url=args.database_url, workspace=root / "factory", question=QUESTION,
                                      evidence_projection=projection)
        def publish(state):
            return publish_synthesis_application(state, QUESTION, projection, author="manager", reviewer="bob")
        mode = "controlled-fixture"
        evidence.update(sourceEvidenceSha256=hashlib.sha256(raw).hexdigest(), sourceTaskId=previous["taskId"],
                        modelExecution="controlled-fixture", sourceEvidenceKind=projection["evidenceKind"])
    try:
        with ExitStack() as stack:
            app = create_app(settings)
            state = app.app.state.factory
            store = state["store"]
            stack.callback(store.engine.dispose)
            stack.callback(store.native_db.db_engine.dispose)
            client = stack.enter_context(TestClient(app))  # type: ignore[arg-type]
            state["auth"].authorization.unassign("bob", "factory-user")
            state["auth"].authorization.assign("bob", "factory-manager")
            application = publish(state)
            binding = state["connections"].bind("alice", REGISTRATION_REF, str(uuid4()), capabilities=[CAPABILITY])

            def request(method, path, body=None, owner="alice"):
                headers = {"Authorization": "Bearer " + state["auth"]._issue_native_token(owner)}
                response = client.request(method, "/api/factory" + path, json=body, headers=headers)
                require(response.is_success)
                return response

            def post(path, body, owner="alice"):
                return request("POST", path, {"requestId": str(uuid4()), **body}, owner).json()

            proposal = post("/compositions/proposals", {"goal": QUESTION, "mode": mode,
                "applicationRef": {key: application[key] for key in ("id", "version", "sha256")},
                "connectionRefs": {CONNECTION_NAME: binding["ref"]}})
            require(proposal["candidate"]["status"] == "ready")
            plan = post("/compositions/proposals/" + proposal["id"] + "/accept", {})
            if settings.temporary_policy == "admin-review":
                review = post("/plan-reviews", {"planId": plan["id"]})
                post("/plan-reviews/" + review["id"] + "/decision", {"approved": True}, "manager")
            request_id = str(uuid4())
            task = post("/instances", {"planId": plan["id"], "requestId": request_id})["id"]
            evidence.update(taskId=task, planId=plan["id"], requestId=request_id)
            def stop_unfinished():
                if evidence["status"] != "completed":
                    try:
                        request("POST", "/jobs/" + task + "/cancel", {"commandId": str(uuid4())})
                        evidence["cancellationRequested"] = True
                    except Exception:
                        evidence["cancellationRequested"] = False
            stack.callback(stop_unfinished)
            require(request("GET", "/requests/" + request_id).json()["taskId"] == task)
            evidence["receiptVerified"] = True
            deadline = time.monotonic() + 90
            while True:
                detail = request("GET", "/jobs/" + task).json()
                if detail["job"]["status"] in {"completed", "failed", "unknown", "canceled"}:
                    break
                require(time.monotonic() < deadline)
                time.sleep(.2)
            evidence["nativeStatus"] = detail["job"]["status"]
            require(evidence["nativeStatus"] == "completed")
            evidence["artifacts"] = []
            for item in detail["artifacts"]:
                raw = request("GET", f"/jobs/{task}/artifacts/{item['id']}").content
                require(hashlib.sha256(raw).hexdigest() == item["sha256"])
                evidence["artifacts"].append({key: item[key] for key in ("id", "name", "sha256")})
                if item["name"] == "literature-synthesis.json":
                    evidence["synthesis"] = json.loads(raw)
            require(bool(evidence["artifacts"]))
            if args.phase == "retrieval":
                evidence["literatureEvidence"] = detail["literatureEvidence"]
                require(detail["literatureEvidence"]["status"] == "ready")
                require(detail["literatureEvidence"]["evidenceKind"] == "public_literature_excerpt")
            else:
                require("synthesis" in evidence)
            usage = store.usage_ledger.inspect("alice", task)
            evidence["usage"] = {"attemptStates": [row["state"] for row in usage["attempts"]],
                "taskScopes": [{key: row[key] for key in ("settledTokens", "heldTokens")}
                               for row in usage["scopes"] if row["scope"] == "task"],
                "providerCalled": False}
            require(bool(evidence["usage"]["attemptStates"]))
            require(all(value == "SETTLED" for value in evidence["usage"]["attemptStates"]))
            require(bool(evidence["usage"]["taskScopes"]))
            require(all(row["heldTokens"] == 0 for row in evidence["usage"]["taskScopes"]))
            evidence["status"] = "completed"
    except Exception:
        evidence["errorCode"] = "PUBLIC_RESEARCH_ACCEPTANCE_FAILED"
    with (root / "result.json").open("x") as stream:
        json.dump(evidence, stream, indent=2)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("retrieval", "synthesis-fixture"), required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--evidence-directory", required=True)
    parser.add_argument("--source-evidence")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        try:
            result = run(args)
        except Exception:
            result = {"status": "stopped", "errorCode": "PUBLIC_RESEARCH_SETUP_FAILED"}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
