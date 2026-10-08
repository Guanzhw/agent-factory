# Unintegrated tokenizer preparation checkpoint

This branch preserves an unfinished storage primitive separately from PR40.
It is not wired into Factory, a runnable bootstrap, a training launcher, or an
accepted managed tokenizer producer. Do not substitute invented task/run/lease
IDs or mocked launch proofs to make it appear runnable.

`ResearchPreparationStore` derives producer identity from an original bounded
process allocation, reserves managed storage, and imports only an original
stopped producer's one-dimensional I32 token-byte tensor. The preparation manifest
is independent of the later training manifest, avoiding the output-hash cycle.
Its proof shape still needs a real fixed provider/harness implementation.

Current evidence: seventeen controlled filesystem/mock tests and static checks
passed; independent review repeated all seventeen tests. Retention/admission/task
lock ordering, fresh authority checks and confirmed hold updates are covered by
controlled tests. The baseline includes PR40's transaction-aware PlanPolicy read
fix. No PostgreSQL, GPU, ML or target execution validates this primitive yet.

Remaining work before integration:

- Implement and verify a fixed preparation provider/harness over the existing
  bounded process lifecycle, producing the exact original-allocation proof.
- Add the trusted controller's actual dispatch cancellation fence and genuine
  preparation task, plan, native run, lease and managed output binding.
- Verify PostgreSQL concurrency, size-one metadata pool, terminal hold release,
  lost acknowledgements and cleanup, then derive the final training inputs.
- Re-run complete exact-head CI after integration. This preservation checkpoint
  does not request another heavy CI pair while PR40's pair is running and is not
  final acceptance. Do not merge or deploy it.
