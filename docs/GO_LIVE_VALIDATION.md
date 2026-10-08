# Bounded Go validation — 2026-10-03

## Actual result

The operator checked only that `OPENCODE_GO` was nonempty (`true`). No key value,
length, hash or fragment was emitted or persisted. The user explicitly attested
**Use balance OFF** and **Auto-reload OFF** and authorized genuine public/synthetic
coding development. This is user attestation, not an independently read invoice.

One DeepSeek smoke attempt was reserved and attempted. It ended **UNKNOWN** with
no confirmed returned model ID or usage. The entire campaign stopped. The available
evidence does not identify the transport/protocol root cause or prove successful
provider processing. No retry was made. GPT-6-Luna had **zero attempts**. There is
no successful live Factory task, tool receipt, artifact or live PG usage settlement.
No claim of zero external charge is inferred from unknown usage or account balance.
The persistent UNKNOWN slot is not released. No new live campaign is authorized by
this result; another request requires an explicit follow-up decision.

| Requested model | Reserved attempts | Confirmed usage/model | Result |
| --- | ---: | --- | --- |
| deepseek-v4-flash | 1 | Unknown / unconfirmed | Smoke stopped; no product task |
| gpt-6-luna | 0 | Not observed | Not attempted |

Private runtime evidence remains outside Git at
`/workspace/scratch/go-live-20261003/evidence.json` and `campaign.sqlite`.
The dedicated PostgreSQL database is retained; neither campaign nor database is
a disposable mock. Public evidence contains only the bounded aggregate above.

## Implemented controls

`Settings(development_live_validation=True)` is operator-only and requires the
explicit demo coding profile and one worker. It is not enabled by environment
configuration or a user prompt. Default subscription preflight remains denied.
A private SQLite campaign binds owner, account attestation, expiry, exact models,
stable sessions and one smoke followed by two product calls per model, DeepSeek
first. Atomic tickets are committed before credentials/HTTP. INFLIGHT/UNKNOWN
slots survive restart; there is no reset/resume API or transport retry.

The sole operator runner is `scripts/run_go_live_validation.py`; it requires
explicit execute and account-attestation flags, a dedicated database, a fixed
evidence directory and confirmation ID. The same path is inspection-only on
repeat. It does not provision credentials or change account settings. Models use
fixed official endpoints, honest Agent Factory User-Agent, stable conversation
headers, separate Chat/Responses parsing, 60-second deadline, 256 output-token cap,
8 KiB serialized input cap and only the checksum coding tool. This byte envelope
is a bounded experiment, not a verified live tokenizer/invoice contract. Queue,
SDK and transport retries are zero. Auth/quota/unknown usage/model mismatch stop
all remaining models. Production research selection is independent.

Known valid usage survives model mismatch, overbound response and HTTP cleanup
failure/cancellation; uncertain usage retains holds. The observer can recheck the
same process's in-flight authority without authorizing another dispatch. A
reopened campaign cannot replay an existing in-flight ticket.

## Offline acceptance (distinct from live)

- Gate/transport tests exercise both wire protocols, exact model IDs, concurrent
  admission, restart denial, global stop, known/unknown accounting and cancellation.
- Actual PostgreSQL/native Factory acceptance passes both models with synthetic
  MockTransport: six bounded requests, normal material/application governance,
  immutable plans, receipts, native checksum artifact and two SETTLED PG attempts
  per model. Both native tickets have attempt=max_attempts=1 (8.176 seconds).
- Final offline suite: 650 tests, 298 explicit skips, 45.461 seconds.
- Existing actual loopback HTTP/PostgreSQL Go cases: 7/7 passed in 46.958 seconds.
- Ruff/Pyright pass. Frontend lint/typecheck/test/build pass; npm audit reports zero
  vulnerabilities. Exact commit CI is recorded in the draft PR, not inferred from
  earlier commits.

Official mapping and scope were checked at [Go documentation](https://opencode.ai/docs/go/):
`deepseek-v4-flash` uses Chat Completions; `gpt-6-luna` uses Responses. The user requested `deepseek-flash`, but this runner selected `deepseek-v4-flash`
without proving equivalence. This selection discrepancy and the mandatory explicit
future version choice are documented in [diagnostics correction](GO_SAFE_DIAGNOSTICS.md).
No production/research traffic or coding-agent impersonation is claimed.


An intermediate full-suite rerun exposed an older ORX concurrency fixture race:
when a second instance reads status after the first launches, `ALREADY_RUNNING`
is the correct fail-closed outcome. Two deterministic interleavings now test
exclusive intent competition and late status separately; both require exactly one
real subprocess launch. No production deadline/retry behavior changed. Independent
review passed. The affected 16-test file passed in 3.319 seconds.

A subsequent execution-shell disconnect did not reset this campaign. After shell
recovery, SQLite and the saved JSON evidence matched exactly: STOPPED/UNKNOWN,
DeepSeek 1, Luna 0. No live runner process remained; zero new requests were sent.


The [offline diagnostics correction](GO_SAFE_DIAGNOSTICS.md) adds safe prospective
events. It neither recovers missing historical facts nor changes this UNKNOWN slot.
