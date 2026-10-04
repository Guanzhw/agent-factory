# Ongoing Go project integration — 2026-10-04

This stage continues PR20 (`bcede60aa6b911969d4200d83eda4ad5f2b574ab`).
The user authorized ongoing DeepSeek/Luna subscription development for this
project and confirmed balance fallback and auto-reload disabled. Earlier
three-request and one-more-request rules remain historical evidence, not the
current admission policy. No payment, paid fallback, account change or new
credential is authorized. Production/research selection remains independent.

## Durable admission

`GoProjectCampaign.migrate` upgrades the existing cumulative budget in place.
It preserves the original three UNKNOWN ticket rows, old session mappings and
journal prefix, recording the policy change separately. It never starts a new
history or converts unknown usage into settled usage. Reopening cannot clear a
stop or acquire an existing in-flight ticket. One request may be in flight;
requests retain exact model/session/purpose binding, bounded bodies/output,
60-second transport timeout and no retries. Auth, quota and billing stops cannot
be cleared by a protocol-review acknowledgement.

Only the coordinator reads runtime `OPENCODE_GO`; workers use synthetic
credentials. Presence/nonempty was true. No value, length or digest was recorded.
The fixed official Go endpoint uses verified TLS, honest Agent Factory User-Agent
and a stable `x-opencode-session`. Chat Completions and Responses use separate
parsers. Official scope: [OpenCode Go](https://opencode.ai/docs/go/).

## New observed requests

| Ordinal | Exact model | Result | Authoritative tokens (input/output/total) |
|---|---|---|---|
| 4 | deepseek-flash | HTTP200; STREAM_USAGE_REPEATED; UNKNOWN | Unknown |
| 5 | deepseek-flash | HTTP200, EOF, PARSED, SETTLED; finish stop | 56 / 69 / 125 |
| 6 | gpt-6-luna | HTTP200, EOF, PARSED, SETTLED; finish completed | 31 / 69 / 100 |

The first new failure identifies the repeated-usage guard, but retained evidence
cannot establish that its repeated counters were identical. The reviewed fix
accepts only individually valid, identical repeated token triples idempotently;
conflicting or malformed repetitions still reject. Neither duplicate counters
nor partial streams settle early: the protocol terminal marker and EOF are required. The failed ticket
remains UNKNOWN, and an explicit reviewed protocol-stop acknowledgement precedes
new requests. Earlier failures are not retrospectively diagnosed or relabeled.

## Factory accounting and product proof

The exact `deepseek-flash` model now has its own governed development registration;
no equivalence to the versioned model is assumed. New Go tariff revisions carry
`accountingBasis=operator-nominal-not-invoice`; existing revisions/hashes remain
unchanged. These nonzero rates exercise internal reservations, not provider
invoice calculation. Persisted task inspection explicitly reports invoice
unverified and actual cost UNKNOWN. Token usage can be authoritative while
actual billing remains unverified.

The project workflow runner publishes reviewed materials and application, binds
an owner connection, accepts an immutable plan, submits one native Agno job,
checks the request receipt, executes checksum over public synthetic Python code,
verifies the artifact hash and inspects two settled model attempts with no
remaining task hold. This is coding development, not scientific synthesis.
Both exact models passed the isolated PostgreSQL/native mocked integration (one
test, 8.995 seconds). Both then passed the actual live runner: DeepSeek settled
1,454 tokens and Luna 931 tokens across two model attempts each. Both receipts
verified, native attempt count was one, held tokens were zero, and the downloaded
checksum artifact matched SHA-256
`6be12a3d672c142f71fbf442c5ed92d3e94f59b7bd0e25be65332a1f15ba0e7f`.

Cumulative history is ten requests: DeepSeek seven, Luna three; four UNKNOWN
and six SETTLED. The policy remains ACTIVE. The original three ticket rows,
legacy sessions, first seventeen journal events, and seven immutable evidence
files (bytes and mtimes) were checked unchanged. Budget/journal growth is
intentional and is not confused with immutable-file preservation.

No merge or deployment. Final exact-head CI and broader product acceptance belong
to the stage draft PR; smoke success alone is not product completion.

Local stage validation: full Python794 tests,299opt-in skips,42.543seconds;
frontend68 tests plus lint/typecheck/build; npm audit zero vulnerabilities;
Ruff/Pyright and independent review passed. The initial full run retained one
stale unregistered-alias assertion; its negative case now uses an actually
unregistered model while exact cross-model rejection remains covered.
