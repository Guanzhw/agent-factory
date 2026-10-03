# Final authorized DeepSeek path validation

This stage follows accepted managed-egress commit
`e90de8a9a7ec69e00b5be896a6888216efcc3997`. The operator authorized one final
independent `deepseek-flash` synthetic coding request. It cannot replay or refund
the two UNKNOWN attempts. The cumulative DeepSeek budget is three, Luna zero.
Billing-off state is user-attested; invoice and account state are not inferred.

`GoFinalSmokeCampaign.authorize_final` uses the same original `.budget.sqlite`
file. An IMMEDIATE transaction creates one immutable final authorization,
retains previous campaign stop facts and both prior ticket records, and grants
only its returning process permission to reserve ordinal three. The old tickets
are immutable. Reopening, changing confirmation IDs, another process, or another
campaign name cannot grant another final authorization. The original stable
session is retained, but the new request receives a distinct UUID.

The dedicated runner requires all explicit flags, invokes the existing adapter
once, and does not run tools or a product workflow. It uses the existing verified
TLS/environment proxy/CA client, fixed official Chat Completions endpoint,
zero retries, 60-second timeout, streaming usage and a 64-token output cap.
Only root's guarded callback reads OPENCODE_GO from runtime environment. No
credential, generated text, raw exception, HTTP body or arbitrary header value
is persisted. Evidence retains allowlisted stages/status/model/finish reason,
usage and cumulative budget counts. Any failure stops; no Luna or PAYG fallback.

A successful new request would validate this path only. It would neither prove
the historical connection-failure root cause nor constitute production identity,
scientific workflow, target-host or billing acceptance. The prior unauthenticated
public GET is not evidence of authenticated inference success.

## Controlled result

Root executed exactly one request using code commit
`081d4de`, at 2026-10-03 09:07:16 UTC. OPENCODE_GO presence was true; no
credential content was printed or persisted. Local request ID:
`c2c80f9d-6d4c-4571-86e8-28e8f5d0851a`.

PREPARED committed at 09:07:16.896973 UTC, DISPATCH_STARTED at
09:07:16.965574 UTC, RESPONSE_HEADERS at 09:07:18.297248 UTC reported HTTP 200
and allowlisted content type event-stream. At 09:07:18.599407 UTC the adapter
recorded ModelProviderError/protocol during the response-reading phase.
STREAM_COMPLETED and PARSED were not reached. Runner stopped at
09:07:18.616829 UTC. No response body or exception text was retained, so a more
specific protocol diagnosis cannot be reconstructed from this evidence.

The new ticket is UNKNOWN. Returned model, finish reason and all usage token
counts are unknown. HTTP 200 alone is not successful inference. DeepSeek is
now 3/3 cumulative reservations; Luna remains 0. The two previous UNKNOWN ticket
rows match their pre-run snapshots exactly; historical campaign/evidence files
match both bytes and modification times. No retry, fallback, Luna request or
product tool roundtrip followed. All live execution is stopped.

Independent pre-dispatch review passed 42 offline tests in 1.257s. Root final
runner/gate tests passed 9/9, historical single-smoke 15/15, HTTP environment
11/11 and provider 26/26; Ruff and Windows-target Pyright passed. No claim is
made about historical failure root cause, subscription charges or model output.
