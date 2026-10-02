# Linux AT10 tree and receiver acceptance

Accepted standalone baseline: `4e1f29900080ad6004fd33f55580b9fe5ea75c37`.
This extension is under active integration in Draft PR11; PR10 remains the earlier checkpoint context. The table distinguishes actual
observations from implementation; it is not a production or real-provider signoff.
The integration owner maintains exact final commit/CI evidence when available.

| Scenario | Actual evidence / current state |
|---|---|
| Standalone acknowledged external work, bounded inference wait, restart, refusal/cancel/revoke/expiry/budget/drift | Accepted at the baseline; original wait and ORX bounds remain unchanged |
| Local child inference pause and service restart | Passed earlier extension run; final regression pending |
| Receiver root inference pause and hard restart | Passed: same native/ORX IDs, one launch, completed, positive kernel stop, two independent services/DBs |
| Receiver child inference pause and hard restart | Passed: original receiver receipt/root ownership plus child native/ORX identity preserved |
| Parent inference fault over live approved child, hard restart | Passed again in the resumed container: explicit separate recovery receipt; original native/ORX identity and one launch; parent and child completed. Actual Chromium Chinese recovery action produced one command POST and no browser errors |
| Receiver parent fault over approved child, hard restart | Still unaccepted in resumed container: inspect can reach approval and parent can reach inference pause, but child native 60-second timeout during inspect/wait invalidates recovery; final combined matrix pending |
| Parent cancellation of waiting child | Passed in the resumed container; original unresolved usage retained |
| Child authoritative overrun under shared ancestor budget | Passed in the resumed container; current usage denial triggered cleanup before the original deadline |
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

## Resumed coordinator diagnosis (2026-10-02)

The new container rebuilt the pinned Linux binary with an exact hash match.
No old scratch path was reused as evidence. Deterministic regressions reproduced
synchronous authority blocking native-loop progress. Async checks now yield to
the loop, retaining fresh authority and a loop-local cancellation fence before
provider/tool entry. Model construction and native pause publication stay on the
loop; canceled preparation cannot publish a late requirement.

Repeated version CLI checks reuse only a successful exact BinaryPin version fact;
permissions and the complete current binary hash are checked on every preflight.
Windows capability detection fails closed without no-follow/nonblocking opens.
Standalone metadata SELECTs use one immediately released autocommit connection;
explicit transactions and durable denial writes keep their original semantics.

Actual receiver-parent attempts remain red: both inspect and later child-wait
native timeout variants were observed. One reached the parent's durable pause
before child failure invalidated it. None is claimed as completed recovery.
Optional fixed-label timing and allowlisted failure snapshots distinguish native
queue state, usage holds and cancellation from synthetic fixture assumptions.
The final exact-commit CI and real runtime matrix are still required.

The resumed local parent/recovery and delegated stop batch passed all three tests
in 370.921 seconds. Browser receipt records one command POST and zero page errors.
The initial integrated Windows CI exposed Linux-mock assumptions in recovery tests;
these now select Linux explicitly, and a separate non-Linux rejection test verifies
fail-closed behavior. Both Windows and Ubuntu Python/frontend jobs passed at
`8d00fbf78d0886f13080f8501516932de1f0d001`; PostgreSQL was still running at recording.

Final resumed-matrix snapshot: 11 cases at `d72a857`, 4 passed/7 preparation
failures in 1358.896 seconds. The failed safety cases never reached fault
injection and remain unaccepted. At `e0ce609`, local parent/browser recovery
passed again, but receiver root/parent failed (3 cases in 424.478 seconds).
The subsequent selected-closure optimization retains fresh material governance
and removes unrelated catalog checks; its actual receiver-parent rerun still
failed at inspect (98.289 seconds). These outcomes supersede any inference of
a green current receiver matrix from earlier passing runs in the table.

The eight safety cases at `2e68725` completed in 1111.150 seconds: 7 passed;
receiver overrun failed during inspect preparation before fault injection. That
case had passed in the prior resumed matrix. Every safety scenario therefore has
a passing current-container run, but the combined batch is still not green.
