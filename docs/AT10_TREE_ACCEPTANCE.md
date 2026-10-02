# Linux AT10 tree and receiver acceptance

Accepted standalone baseline: `4e1f29900080ad6004fd33f55580b9fe5ea75c37`.
This extension is saved as a separate, unaccepted WIP checkpoint; Draft PR10 remains the earlier integration context. The table distinguishes actual
observations from implementation; it is not a production or real-provider signoff.
The integration owner maintains exact final commit/CI evidence when available.

| Scenario | Actual evidence / current state |
|---|---|
| Standalone acknowledged external work, bounded inference wait, restart, refusal/cancel/revoke/expiry/budget/drift | Accepted at the baseline; original wait and ORX bounds remain unchanged |
| Local child inference pause and service restart | Passed earlier extension run; final regression pending |
| Receiver root inference pause and hard restart | Passed: same native/ORX IDs, one launch, completed, positive kernel stop, two independent services/DBs |
| Receiver child inference pause and hard restart | Passed: original receiver receipt/root ownership plus child native/ORX identity preserved |
| Parent inference fault over live approved child, hard restart | Passed locally: explicit separate recovery receipt; original native/ORX identity and one launch; parent and child completed |
| Receiver parent fault over approved child, hard restart | FAILED latest run: child orx_experiment_inspect cancelled before approval; remote-parent recovery has not been accepted |
| Parent cancellation of waiting child | Implemented test; actual acceptance pending |
| Child authoritative overrun under shared ancestor budget | Implemented test; actual acceptance pending |
| Current source account overrun | Passed controlled accounting fault; no provider bill is claimed |
| Source cancellation | Passed, preserving cancellation classification |
| Source connection revocation | Passed before original wait deadline |
| Source outage then restart | Passed isolated final rerun: failed closed, original work stopped, source restart did not relaunch, UNKNOWN usage/grant remained held |
| Original inference wait expiry | Passed, no deadline renewal |
| Receiver authoritative usage overrun | Passed isolated rerun |
| Receiver connection revocation | Passed before original wait deadline |
| Original source drift | Passed: positive process stop with unresolved effect/disk hold retained |

## Native restart boundary

A crash inside an approved child continuation can leave Agno's original native
run/ticket paused at its previous launch confirmation. The original Factory
approval remains acknowledged. Repeating that approval returns its original
receipt and must never secretly dispatch again.

`resume_approved` is a distinct, explicit owner action. It links the original
approval, exact requirement/version, same task/plan/native run and positively
stopped DONE ORX effect. It has a separate durable command receipt and a unique
slot allowing at most one repair per original approval. Current permission,
source, receiver authority and budget checks still apply. Unknown repair
acknowledgement permits receipt reconciliation only.

The bridge uses Agno's public `acontinue_via_queue` paused-to-queued CAS on the
same ticket. Missing, terminal, foreign or conflicting tickets cannot fall back
to detached HTTP execution. The original experiment result is reused read-only;
no namespace wake, second ORX launch, owner replacement or failed-row rewrite is
allowed. Later inference remains subject to fresh ledger admission.

Parent fault fixtures use the existing registered native `ask_scope` tool and
reviewed test materials. The parent pauses during child preparation, then the
owner answers after the independently approved child acknowledges its real
launch. The next controlled model call raises 503. This tests an actual bounded
inference leg without stretching the original 60-second native execution bound,
30-second inference wait or admitted ORX limits.

## Reproduction and evidence

Use the pinned ORX/isolated PostgreSQL prerequisites in [LINUX_ORX.md](LINUX_ORX.md).
On hosts whose `/tmp` is too small for admitted disk reservations, set
`FACTORY_AT10_FIXTURE_ROOT` to an owned filesystem with sufficient space; do not
lower the resource admission or low-water limits.

```sh
PYTHONPATH=platform:platform/tests .venv/bin/python -m unittest \
  test_inference_wait test_approved_recovery test_opencode_go -v
# Explicit real Linux ORX and generated loopback PostgreSQL opt-in required:
FACTORY_ORX_LINUX_CONTAINER=1 PYTHONPATH=platform:platform/tests \
  .venv/bin/python -m unittest test_actual_inference_tree -v
```

`FACTORY_AT10_TREE_EVIDENCE_DIR` optionally stores public synthetic identity/stop
receipts and owned service logs. Generated database/JWT configuration remains
outside the repository. Heavy real-runtime tests run serially on the measured
4 CPU / 16 GiB host. CI without these prerequisites skips them explicitly.

Remaining production gates include real approved model/provider and billing
policy, production identity/TLS, controlled mutable/non-toy research, Windows
coverage, sustained department concurrency, and user-authorized production host
capacity. The development Go transport remains unregistered and billing-gated;
see [OPENCODE_GO.md](OPENCODE_GO.md). No paid model/compute or production access
is established by this matrix.
