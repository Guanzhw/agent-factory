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

## Offline diagnosis of the retained result

Only the safe journal and adapter code at `329236ccf6e96bbc9b9b8755105486e97286bcac`
are available for the third request. The journal schema stores phase, finite
error class/category and selected HTTP metadata; it does **not** store an
exception cause chain, parser rejection code, event count, response body or
stream suffix. There is no additional persisted chain to inspect or recover.

The recorded signature is RESPONSE_HEADERS + ModelProviderError/protocol +
stop UNKNOWN. The client calls `_Stream.feed` during `response.aiter_bytes()`
and only records STREAM_COMPLETED after iteration finishes. Accordingly:

- A direct HTTPX truncation/read/timeout exception has its own allowlisted type,
  unlike the recorded ModelProviderError.
- Normal EOF without a terminal marker reaches STREAM_COMPLETED before
  `_Stream.finish` rejects it, unlike this request.
- JSON decoding failure during feed has JSONDecodeError/parse, unlike this
  request. A malformed Python structure has its corresponding safe error type.
- A model change across chunks has MODEL_MISMATCH as its stop code, unlike the
  recorded UNKNOWN.
- Several explicit feed guards share the observed signature: an application
  error event (including an unknown auth/quota reason inside HTTP 200), early or
  repeated usage, choices after a terminal choice, data after completion,
  invalid choice/tool shape, and the total body-size guard.

These distinctions narrow compatible code paths; they do not establish which
one occurred, exclude every possible network influence, or prove a provider/SDK
compatibility issue. The final response parser and Agno ModelResponse conversion
were not reached. A null saved finishReason does not prove that the stream lacked
a finish_reason: the runner only observes it after full stream assembly.

No body has been reconstructed and no extra external diagnostic request was
made. All three UNKNOWN tickets and their budget accounting remain unchanged.
No runtime assertion or parser behavior is relaxed on the basis of hypotheses.

Synthetic characterization also demonstrates a separate framing limitation:
multiple `data:` lines containing one multiline JSON SSE event are decoded
line-by-line and fail with JSONDecodeError/parse. That distinct signature does
not match this retained request. This is an explicit compatibility limitation,
not a diagnosed explanation for the live failure; this follow-up does not
change framing semantics or claim to repair the live root cause. Normal
fragmented chunks, CRLF and comment heartbeats succeed in the fixtures.

Offline follow-up validation: the new 11-case characterization suite uses exact
`deepseek-flash`, synthetic imported UNKNOWN history and MockTransport only.
Independent review passed those 11 cases plus 25 related tests. Root full
non-Postgres collection passed 748 tests in 49.443s with 298 skips; Ruff and
Windows-target Pyright passed. Only tests/documentation changed. Final exact-head
CI and pass/skip counts are recorded in PR19.
