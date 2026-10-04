"""One synthetic coding invocation in the durable project subscription policy.

Ongoing project authorization is held by the policy, not by artificial batches.
This CLI never retries, resumes a stopped policy, or resets any UNKNOWN ticket.
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

from agno.models.message import Message
from agent_factory.go_diagnostics import safe_diagnostic
from agent_factory.go_project_campaign import GoProjectCampaign
from agent_factory.opencode_go import GoDevelopmentModel

PROMPT = "Coding development smoke: return only a Python function add(a, b) that returns a + b. No explanation or tools."
MODELS = {"deepseek-flash", "gpt-6-luna"}


def credential():
    return os.environ.get("OPENCODE_GO", "")


def run(args):
    if args.model not in MODELS or type(args.output_tokens) is not int or not 1 <= args.output_tokens <= 4096:
        raise ValueError("PROJECT_SMOKE_CONTRACT")
    directory = Path(args.evidence_directory).absolute()
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    # A reused output directory refuses before any campaign or credential access.
    campaign = GoProjectCampaign(args.budget_path)
    session = "project-coding-smoke-" + args.model
    evidence = {"execution": "project-coding-smoke", "model": args.model,
                "accountSettings": "user-attested-off", "invoiceVerified": False,
                "pricingStatus": "UNKNOWN", "finishReason": None, "status": "stopped"}

    class ObservedModel(GoDevelopmentModel):
        def _parse_provider_response(self, response, **kwargs):
            if type(response) is dict:
                if self.id == "gpt-6-luna":
                    reason = response.get("status")
                else:
                    choices = response.get("choices")
                    reason = choices[0].get("finish_reason") if type(choices) is list and len(choices) == 1 and type(choices[0]) is dict else None
                if type(reason) is str and reason in {"stop", "length", "tool_calls", "content_filter", "completed", "incomplete", "failed"}:
                    evidence["finishReason"] = reason
            return super()._parse_provider_response(response, **kwargs)

    try:
        if campaign.journal is None:
            raise ValueError("DIAGNOSTICS_REQUIRED")
        campaign.journal.record("runner", "RUNNER_STARTED")
        campaign.authorize(session, args.model, purpose="smoke", owner_id=args.owner_id)
        model = ObservedModel(model_id=args.model, session_id=session, credential=credential,
            live_campaign=campaign, max_output_tokens=args.output_tokens, timeout_seconds=60,
            wire_stream=True, native_retries=0)
        # Exactly one invocation; the generated content is deliberately discarded.
        asyncio.run(model.ainvoke([Message(role="user", content=PROMPT)]))
        latest = campaign.inspect(include_diagnostics=False)["tickets"][-1]
        if latest["state"] != "SETTLED" or latest["actual_model"] != args.model or latest["error_code"] is not None:
            raise ValueError("SETTLEMENT_REQUIRED")
        evidence["status"] = "completed"
        campaign.journal.record("runner", "RUNNER_COMPLETED")
    except BaseException as error:
        evidence["diagnostic"] = safe_diagnostic("RUNNER_FAILED", error=error)
        # Preserve the provider's AUTH/QUOTA/other first stop reason.
        if campaign.inspect(include_diagnostics=False)["status"] != "STOPPED":
            campaign.stop("CANCELLED" if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt)) else "UNKNOWN")
        if campaign.journal is not None:
            campaign.journal.record("runner", "RUNNER_FAILED", error=error)
            campaign.journal.record("runner", "RUNNER_STOPPED")
    evidence["campaign"] = campaign.inspect()
    with (directory / "smoke-evidence.json").open("x", encoding="utf-8") as handle:
        json.dump(evidence, handle, indent=2)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("budget-path", "owner-id", "model", "evidence-directory"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--output-tokens", type=int, default=512)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        try:
            result = run(args)
        except BaseException as error:
            result = {"status": "setup-failed", "diagnostic": safe_diagnostic("RUNNER_FAILED", error=error)}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
