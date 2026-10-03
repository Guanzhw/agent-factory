# Safe Go rejection diagnostics

This bounded offline follow-up closes the attribution gap identified in PR19.
It changes diagnostic metadata only. Parser acceptance, exception messages and
HTTP status codes, fixed endpoints, TLS/proxy handling, retries, usage settlement,
request budgets and historical evidence are not changed. New wrapper diagnostics
can now retain a more specific underlying error type/category where the previous
implementation reported only a generic provider error; public exception
type/message/status compatibility is preserved.

Future error diagnostics retain the existing `phase`, `errorType` and
`errorCategory` fields and add:

- `rejectionCode`: one stable enum from `go_diagnostics.REJECTION_CODES`, assigned
  at the actual adapter validation throw site. It is never derived by matching
  exception text. Direct transport/JSON/structure exceptions have fixed type-based
  fallback categories; unrecognized types become UNKNOWN_ERROR.
- `exceptionChain`: at most six fixed allowlisted class names along one
  cause/context spine. Unknown classes become UnknownError. This is not a full
  traceback, exception-group graph or exception-message record. Wrapping preserves
  the bounded original diagnostic metadata even when Python context is suppressed.

The existing journal serializes these fields for newly recorded failures without
schema migration. Reading old journal entries returns their original metadata;
no rejection cause is inferred or backfilled. The three historical UNKNOWNs
remain UNKNOWN and continue to occupy the full DeepSeek three-request budget.

Stream size, data after completion, model changes, separate Responses failure
kinds, Chat error objects, choice shape/count/index, choices after terminal,
tool index/type, early/repeated usage and incomplete/missing terminal conditions
have distinct explicit codes. Response and tool validation failures also carry
fixed codes. No valid/invalid response acceptance boundary is relaxed, including
the previously characterized multiline-SSE limitation.

Metadata access bypasses exception subclass properties. Code/chain metadata is
revalidated before output; cycles and long chains are bounded. No exception text,
raw headers, prompts, generated content, credentials, body or arbitrary class
name is captured. Existing finite HTTP status/header categories remain unchanged.

## Smallest proposed future live validation — not authorized or run

After a separate explicit authorization for one additional request, use one
synthetic coding smoke with exact deepseek-flash, 64 output tokens, 60-second
timeout, zero retries and no tools through the existing verified proxy/CA and
fixed official endpoint. Preserve all three prior UNKNOWNs and reserve a distinct
new request in cumulative accounting before credential access; do not reopen or
reset the exhausted batch. Retain only the new safe rejection code, stage,
class-name chain, HTTP status, returned allowlisted model/finish and usage.
Stop after that one request regardless of outcome. No Luna, product roundtrip,
PAYG fallback or automatic retry is proposed. This document grants no new live
or billing authorization.

## Offline validation

All 18 explicit stream rejection outcomes have distinct throw-site fixture
coverage. Real synthetic campaign/journal tests distinguish read/protocol
transport errors, JSON failure, missing terminal and incomplete buffer while
retaining UNKNOWN slots. Redaction tests cover malicious exception names,
properties, dictionary-subclass hooks, forged metadata, cycles, long causal
chains, exception-group boundaries and causes attached only during raise.

Final focused suite: 16 tests passed. Independent review passed 76 related tests
before the last bounded-chain regression, then independently passed the final
16-test suite. Root full collection: 764 tests, 298 skipped, 44.627s, all passing.
Ruff and Windows-target Pyright passed. Source credential-pattern scan found no
matches. Nine protected historical/budget/evidence files retain their original
bytes and modification times. Exact-head CI is recorded in the draft PR.
