# P6 curated start-record verification

Base: `f25c8992f5c286db3cca3554e3c74a255dfe9f82` (Draft #111, not main).
Code head: `cbc4dc1e9f39e64273bf9a8cc665cf4c55fdad71`.

The admission transaction now publishes one immutable, team-readable curated
`pending_admission` snapshot. It includes objective, conditions and domain IDs,
not connection configuration, credentials or conversation history. Current core
sharing remains authoritative. Replaying the original request does not publish
again or restore withdrawn sharing. No recipient selector exists yet, so this
slice sends no event or broadcast.

## Executed checks

- Existing research run tests plus curated-record portable cases: 9 passed,
  zero skipped, 1.228s; `test_research_runs test_research_records`.
- Real isolated PostgreSQL `test_research_records_postgres`: 2 passed,
  zero skipped, 12.059s. Concurrent original request deduplication, two-user
  read/write boundaries and transaction rollback executed. An actual native
  task completes without changing this initial snapshot into a live result.
- Ruff and whitespace checks passed.
- Author-independent full base/head review by `foundation_review`: passed.
  Review covered all nine spec/source/test files. The stale P5 description was
  corrected before the exact-head review; no remaining blocking findings.

Local first-run logs: `/tmp/research-start-records-portable-first.log` and
`/tmp/research-start-records-pg-first.log`. These local paths are provenance,
not user-download links. CI status belongs to the precise PR head.

## Remaining acceptance

Terminal research records, autonomous rounds, relevant peer selection and final
reproducible delivery remain incomplete. This is neither full P6 nor real model,
GPU, production identity or research-value acceptance. No UI changed.
