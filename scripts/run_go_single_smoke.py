"""One explicitly authorized synthetic smoke; existing budgets are inspection-only.

The exact model is deepseek-flash. This does not map or validate any other model
name. The operator credential callback is invoked only by the guarded adapter.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import logging
import os
from pathlib import Path
from uuid import uuid4
import time

from agno.models.message import Message

from agent_factory.go_diagnostics import safe_diagnostic
from agent_factory.go_single_smoke import GoSingleSmokeCampaign
from agent_factory.opencode_go import GoDevelopmentModel

MODEL = "deepseek-flash"
PUBLIC_PROMPT = "Coding development smoke: return only the Python expression 1 + 1."


def credential():
    return os.environ.get("OPENCODE_GO", "")


def require(value):
    if value is not True:
        raise ValueError("Explicit single-smoke authorization required")


def run(args):
    # The imported history determines the sole cumulative budget location;
    # changing campaign/evidence IDs cannot reset its consumed request slots.
    history = Path(args.history_path).absolute()
    budget = Path(str(history) + ".budget.sqlite")
    if os.path.lexists(budget):
        return {"execution": "inspection-only", "campaign": GoSingleSmokeCampaign(budget).inspect()}
    for name in ("execute_authorized_live", "use_balance_off", "auto_reload_off",
                 "synthetic_only", "confirm_one_attempt"):
        require(getattr(args, name, False) is True)
    require(getattr(args, "exact_model", None) == MODEL)
    campaign = GoSingleSmokeCampaign.create(budget, history_path=history,
        campaign_id=args.campaign_id, owner_id=args.owner_id,
        confirmation_id=args.confirmation_id, expires_at=time.time() + 3600,
        use_balance_disabled=True, auto_reload_disabled=True)
    evidence = {"execution": "single-smoke", "model": MODEL,
                "accountSettings": "user-attested-off", "invoiceVerified": False,
                "pricingStatus": "UNKNOWN", "monetaryUpperBound": None,
                "campaign": None}

    def persistence_failure(operation, error):
        evidence.setdefault("diagnosticPersistence", []).append({
            "operation": operation, "status": "failed",
            "diagnostic": safe_diagnostic("RUNNER_FAILED", error=error)})

    def stop_safely(code):
        try:
            if campaign.inspect(include_diagnostics=False)["status"] == "STOPPED":
                return
        except BaseException as error:
            persistence_failure("campaign-stop-facts", error)
        try:
            campaign.stop(code)
        except BaseException as error:
            persistence_failure("campaign-stop", error)

    def record_safely(phase, error=None):
        try:
            if campaign.journal is None:
                raise ValueError("Diagnostic journal required")
            campaign.journal.record("runner", phase, error=error)
        except BaseException as failure:
            persistence_failure(phase, failure)

    phase = "RUNNER_STARTED"
    try:
        if campaign.journal is None:
            raise ValueError("Diagnostic journal required")
        campaign.journal.record("runner", phase)
        session = "single-smoke-" + str(uuid4())
        campaign.authorize(session, MODEL, purpose="smoke", owner_id=args.owner_id)
        phase = "smoke"
        model = GoDevelopmentModel(model_id=MODEL, session_id=session,
            credential=credential, live_campaign=campaign, max_output_tokens=64,
            timeout_seconds=60, wire_stream=True, native_retries=0)
        # Exactly one model invocation. Output content never enters evidence.
        asyncio.run(model.ainvoke([Message(role="user", content=PUBLIC_PROMPT)]))
        phase = "settlement-check"
        facts = campaign.inspect(include_diagnostics=False)
        require(facts["status"] == "DONE" and facts["requestCount"] == 2
                and facts["budgetCounts"]["deepseek"] == 2)
        latest = facts["tickets"][-1]
        require(latest["state"] == "SETTLED" and latest["actual_model"] == MODEL
                and latest["error_code"] is None)
        phase = "RUNNER_COMPLETED"
        campaign.journal.record("runner", phase)
        evidence["status"] = "completed"
    except BaseException as error:
        evidence["status"] = "stopped"
        evidence["stoppedPhase"] = phase
        evidence["diagnostic"] = safe_diagnostic("RUNNER_FAILED", error=error)
        if phase in {"RUNNER_STARTED", "RUNNER_COMPLETED"}:
            persistence_failure(phase, error)
        stop_safely("CANCELLED" if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt)) else "UNKNOWN")
        record_safely("RUNNER_FAILED", error)
        record_safely("RUNNER_STOPPED")
    try:
        evidence["campaign"] = campaign.inspect()
    except BaseException as error:
        persistence_failure("campaign-inspect", error)
        try:
            evidence["campaign"] = campaign.inspect(include_diagnostics=False)
        except BaseException as failure:
            persistence_failure("campaign-facts", failure)
    try:
        directory = Path(args.evidence_directory).absolute()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        # No overwrite of an earlier run's public evidence, including failure.
        with (directory / "single-smoke-evidence.json").open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(evidence, indent=2) + "\n")
    except BaseException as error:
        persistence_failure("evidence-write", error)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("execute-authorized-live", "use-balance-off", "auto-reload-off",
                 "synthetic-only", "confirm-one-attempt"):
        parser.add_argument("--" + name, action="store_true")
    parser.add_argument("--exact-model", help="New execution requires exactly deepseek-flash")
    for name in ("history-path", "campaign-id", "owner-id", "confirmation-id", "evidence-directory"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        try:
            result = run(args)
        except BaseException as error:
            result = {"status": "operator-setup-failed",
                      "diagnostic": safe_diagnostic("RUNNER_FAILED", error=error)}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
