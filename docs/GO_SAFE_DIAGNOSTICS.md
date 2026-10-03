# Go diagnostics correction — offline only

This continuation starts at PR15 head
`45eeb6b88046a40f8743e01e69d10353be386499`. It does not retry the stopped live
campaign, contact support, inspect private provider APIs or discover credentials.
The historical smoke ticket and all three saved evidence files remain unchanged.
New diagnostics cannot retrospectively recover the lost HTTP facts.

## Model-selection correction

The user wrote `deepseek-flash`. The historical campaign selected
`deepseek-v4-flash`: its saved ticket has that exact model, PR15's runner iterated
`go_live.MODELS`, and the adapter constructed `body["model"] = self.id`. There is
no runtime alias resolution or fallback in that code. Since no wire metadata or
returned model identity was retained, this proves the locally selected/prepared
model, not service receipt or the provider's actual model.

The earlier checkpoint documentation explicitly said the public catalog contained
both names but did not establish the alias target. The coordinator nevertheless
selected the concrete v4 version. An earlier commentary named that choice, but
announcing a choice is not evidence of equivalence or an explicit exact-version
selection by the user. This was a selection discrepancy; it must not be described
as successful validation of the user's `deepseek-flash` model. The older wording
about “no undocumented alias” did not adequately disclose this distinction.

Future new executions require an explicit `--exact-model-sequence` equal to the
supported exact sequence. There is no default, alias translation, fallback or
automatic substitution. The flag records an operator's deliberate version choice;
it does not create user authorization or prove the alias mapping. Existing campaign
inspection needs no selection and cannot dispatch. Actual use of `deepseek-flash`
remains unresolved; this offline change does not enable it or select another model
on the user's behalf.

## Diagnostic meaning and privacy

Fresh campaigns get a separate append-only SQLite event journal. Existing campaign
files are not migrated or backfilled. Without an existing journal, a legacy campaign
is inspection-only and cannot begin another dispatch. Each event is synchronously
committed; failed diagnostic persistence stops further execution while keeping the
reserved attempt. A crash cannot reset or replay a budget.

| Recorded phase | What it establishes | What it does not establish |
| --- | --- | --- |
| PREPARED | A local attempt slot has been reserved | Credential access, network sending or provider receipt |
| CREDENTIAL_CHECK | Local credential validation is about to run | Valid credentials or any network effect |
| DISPATCH_STARTED | Entering the local HTTP operation | Socket bytes written, service receipt or inference |
| RESPONSE_HEADERS | HTTP response headers were received | Successful model execution or valid usage |
| STREAM_COMPLETED | Response body reading reached EOF | Valid SSE terminator, parsed response or usage |
| PARSED | The adapter accepted the response contract | Successful later cleanup, tools or product acceptance |
| FAILED / UNKNOWN | Recorded failure or unresolved outcome | A refunded slot or permission to replay |

The local ticket UUID is the diagnostic request ID. It is **not a server request
ID**. Provider-controlled request-ID/header strings are not stored. Safe header
metadata uses fixed normalized categories or presence flags, never arbitrary raw
values. HTTP status is a bounded integer; exception types come from an explicit
known-type allowlist and summaries are fixed phrases. Unknown exception classes
stay unknown rather than leaking a dynamic class name or text. No Authorization,
credential, URL/error body, token/output text, raw exception, partial private body,
unknown model string, or hashes/truncations of these values are persisted.

Stages and exception categories separate failures before dispatch, connection,
response reading, protocol/JSON parsing, timeout and cancellation where the local
exception proves that distinction. An abrupt process death leaves only the last
committed stage; its original exception or actual server outcome cannot be
invented. Reopening reads that evidence without synthesizing a success or retry.
The original UNKNOWN campaign remains UNKNOWN.

## Historical diagnosis remains limited

The first campaign was created at 2026-10-03 06:16:35.010736 UTC; its local ticket
was created at 06:16:37.494160 UTC. The stopped evidence file was written by
06:16:42.596841 UTC. No actual HTTP start/end timestamp, response status/header,
server request ID, raw safe exception type or confirmed model/usage survives.
It is impossible to distinguish zero sends from a dispatched request with an
unknown outcome. Retaining one UNKNOWN slot is therefore necessary. The native
Factory jobs and PG usage attempts remained zero because the smoke did not pass.

Offline tests and independent review for this continuation are recorded in its
draft PR. They prove diagnostic behavior under synthetic faults, not live service
compatibility or the cause of the historical smoke failure.


## Local acceptance

Independent reviewer: 82 targeted tests passed in 1.895s, no remaining blocker.
Full offline suite: 682 tests / 298 explicit skips, 44.056s. Actual PostgreSQL
native Factory path with synthetic MockTransport: six requests across both model
protocols passed in 9.191s. Ruff/Pyright pass. Old campaign/evidence/stdout file
bytes and modification times match the pre-change manifest; no real request,
private API call or support contact occurred. Final exact-head CI is recorded in
the new draft PR, separately from these local results.
