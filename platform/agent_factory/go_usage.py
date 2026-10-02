"""Explicit development accounting contracts, not proof of subscription billing.

The fixture profile uses nominal, conservatively selected catalogue rates to
exercise nonzero immutable reservations. No external payment is made by this
module. Live profile admission remains blocked pending account-specific proof.
"""
from __future__ import annotations

import json

from fastapi import HTTPException

from .opencode_go import GoDevelopmentModel
from .usage_ledger import PricingRevision, native_response_usage

INPUT_CEILING = 32768
OUTPUT_CEILING = 512


def request_guard(model, arguments, keyword_arguments, commitment):
    if not isinstance(model, GoDevelopmentModel):
        raise HTTPException(409, "GO_REQUEST_CONTRACT: exact development adapter required")
    if (model.retries != model._native_retry_limit or not 0 <= model.retries <= 1
            or not 0 < model._timeout <= 60 or not 1 <= model._cap <= commitment["perAttemptOutputTokens"]):
        raise HTTPException(409, "GO_REQUEST_CONTRACT: approved output/deadline/retry bounds changed")
    messages = arguments[0] if arguments else keyword_arguments.get("messages")
    if not isinstance(messages, list):
        raise HTTPException(409, "GO_REQUEST_CONTRACT: native message list required")
    options = {key: value for key, value in keyword_arguments.items() if key != "messages"}
    options.pop("stream", None)
    body = model._body(messages, stream=model.factory_wire_stream, **options)
    # Deliberately conservative local admission envelope, including tool schemas
    # and message framing. This is fixture-verified; a live tokenizer/accounting
    # contract must be reviewed separately before unblocking network execution.
    bound = len(json.dumps(body, ensure_ascii=False).encode("utf-8")) + 512 * (
        1 + len(messages) + len(body.get("tools", [])))
    if bound > commitment["perAttemptInputTokens"]:
        raise HTTPException(429, "GO_REQUEST_INPUT_BOUND: request exceeds approved input envelope")


def pricing_registrations(adapter_ids):
    # Nominal reviewed catalogue maxima for this <=32K-input development scope,
    # not measured invoice rates or a zero-charge subscription assertion.
    rates = {"deepseek-v4-flash": (300000, 1200000), "gpt-6-luna": (100000, 500000)}
    return tuple(PricingRevision(adapter_ids[model], "1", "opencode-go-development", model,
        "go-development-nominal-2026-10-02-v1", input_micros_per_million=incoming,
        output_micros_per_million=outgoing, per_attempt_input_tokens=INPUT_CEILING,
        per_attempt_output_tokens=OUTPUT_CEILING, usage_reader=native_response_usage,
        request_guard=request_guard) for model, (incoming, outgoing) in rates.items())
