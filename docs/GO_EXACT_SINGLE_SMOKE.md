# Exact DeepSeek continuation

This stage follows PR16 at `f85b02bf7343b7b67c3b3643c922fb9a69ed22ae`.
The operator is authorized to make one new independent short request using
exactly `deepseek-flash`. The old `deepseek-v4-flash` UNKNOWN is permanently
retained, counting toward the same three-attempt DeepSeek allowance. This step
is capped at two cumulative reservations (old one plus new one); no third
request, Luna invocation, native tool loop or account-setting change is allowed.

## Public contract evidence

The [official unauthenticated Go catalog](https://opencode.ai/zen/go/v1/models)
lists `deepseek-flash` separately from the two versioned Flash IDs. The
[official Go route](https://github.com/anomalyco/opencode/blob/dev/packages/console/app/src/routes/zen/go/v1/chat/completions.ts)
accepts `body.model` through the OpenAI-compatible Chat Completions format;
the [official handler](https://github.com/anomalyco/opencode/blob/dev/packages/console/app/src/routes/zen/util/handler.ts)
explicitly includes `deepseek-flash` among Go DeepSeek IDs. These were read on
2026-10-03. Static documentation omission is not evidence of unavailability.

The adapter sends the requested ID unchanged. A different returned ID is retained
only if it belongs to the fixed safe model allowlist, and stops the attempt as a
model mismatch; it does not establish alias equivalence. Usage can be known while
pricing remains UNKNOWN. No versioned-model price is borrowed. Monetary upper
bound remains null, while reserved input/output token bounds and request slots
remain visible. Provider invoice and account state are not independently verified;
the two billing toggles rely on the user's explicit off confirmation.

## Durable one-attempt boundary

`GoSingleSmokeCampaign` imports only the safe facts of the specified stopped
historical campaign, requiring the same owner and exactly one UNKNOWN. The
source file and old evidence are never written. The new budget is always at
`<authorized-history-path>.budget.sqlite`, independent of new campaign IDs or
evidence directories; root fixes that historical path for this authorization.
This does not claim to prevent a malicious filesystem owner from copying or
tampering with files. Such copies are not authorized histories.

SQLite IMMEDIATE reservation serializes competing callers. Imported facts cannot
be updated/deleted, reservations cannot be deleted, and cancellation or restart
never refunds a slot. Only the process that creates the continuation owns its
new reservation; reopening is inspection-only, even after a crash before sending.
The new local request UUID differs from the historical UUID. A committed PREPARED
is not evidence of network transmission. A journal failure before dispatch stops
the attempt without credential access. First recorded stop reason is preserved.

`scripts/run_go_single_smoke.py` requires explicit live, billing-off, synthetic,
one-attempt and exact-model flags. It invokes the model once, stream mode enabled,
retry zero, timeout 60 seconds, output at most 64 tokens, with a fixed public
synthetic coding prompt and no tools. Existing budget paths are inspected only.
The root operator alone reads OPENCODE_GO at the guarded credential callback;
workers use mocks. Output text, credentials and arbitrary HTTP metadata are not
written to evidence. Safe transport stages, status, fixed header categories,
error classification, returned allowlisted model and usage are retained.

Offline tests, independent review, safe live outcome and exact-head CI are recorded
in the continuation PR. No success here establishes production or scientific
workflow acceptance.

## Controlled attempt outcome

After independent review and offline validation, root executed the one authorized
new exact-model smoke on 2026-10-03. The local request ID is
`aa945eb2-fdf5-432e-8237-c1c9f09c7bb9`, distinct from the imported historical ID.
PREPARED committed at 07:56:06.524046 UTC; DISPATCH_STARTED at
07:56:06.565807 UTC. At 07:56:11.638040 UTC, the journal recorded ConnectError
(connection category) at DISPATCH_STARTED, then FAILED and RUNNER_STOPPED.
No RESPONSE_HEADERS event was observed. HTTP status, returned model and usage
remain unknown. This establishes a local connection exception, not server
receipt or the network/DNS/TLS cause. The exception text/body was not stored.

The new attempt is UNKNOWN and permanently occupies its slot. The cumulative
DeepSeek count is two (old versioned UNKNOWN plus new exact-ID UNKNOWN), Luna
count zero. No retry, native execution or other model call followed. Pricing
remains UNKNOWN; no invoice or subscription consumption was inferred. The three
historical evidence files retain their original bytes and modification times.

Validation before this attempt: independent review found no blocker, 44 targeted
tests passed in 0.903s; full offline collection ran 704 tests with 298 skips in
52.616s. A subsequently added missing-usage case was included in a separate
six-case exact-ID suite (0.111s). Ruff and Windows-target Pyright passed. No
credential patterns were found in the nine changed files. Final integrated CI
is recorded in the draft PR, without conflating offline mocks with live success.
