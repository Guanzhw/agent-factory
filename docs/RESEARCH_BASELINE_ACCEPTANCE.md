# First real local baseline accepted — 2026-10-07

**COMPLETE for the selected local baseline.** The local execution owner verified
this result at **09:48 UTC on 2026-10-07** and supplied the sanitized final
handoff. This public record reconciles that owner-verified evidence; the cloud
coordinator did not rerun the GPU job or independently fetch private artifacts.
It is one real baseline result, distinct from synthetic tests and cloud CI.

## Exact execution and result

| Item | Verified local outcome |
|---|---|
| Runner | PR54 `df2c40bfe4993db722592264c26b8842178f48b4` |
| Sealed installed Factory runtime | PR50 `997013114a8c533c84078d174b220e541ea19f9a` |
| Selected upstream | `karpathy/autoresearch` at `228791fb499afffb54b46200aca536f79142f117` |
| Device/profile | RTX 5070, SM 120, 12 GB; SDPA; microbatch 1 |
| Scientific inputs | Original fixed dataset, tokenizer and evaluator; no replacement protocol |
| Counted training | 302.587995 seconds after 11 warmup steps |
| Full original evaluation | `val_bpb = 1.6711944975804394` |
| Training and evaluation | Both `COMPLETED`, exit 0 |
| Attempt policy | Single attempt, zero retries in this successful run |
| Checkpoint | 159392448 bytes; SHA256 `614c51598bdb905dad9486724c8e51eedce2ad4f1db21984f6b6bf90004ea5c5` |
| Final local manifest | SHA256 `a35b53432a056341282987c9fc9dab6da545d5e9ebd541a76e6db8ec153dfac1` |

The counted training time follows the original accumulated-step timing protocol,
which excludes warmup and stops at a step boundary. It is not total job wall time.
Full evaluation coverage was verified through the fixed source and independent
evaluator custody, **not an added independent token counter**. The score is a
baseline observation under this local protocol, not a candidate improvement,
scientific discovery or cross-hardware ranking.

## Custody and preservation

C/C++ compiler smoke and both preflights passed. Training and evaluation stage
journals and PostgreSQL audits both passed. The lease, allocation, GPU and native
claim were verified **RELEASED**. The final local check found no remaining task
process, GPU compute, temporary authorization directories or claim locks.
Unknown/missing ACK fields were preserved and were not replayed to manufacture
acknowledgements.

The original sealed runtime/source and all older evidence remain unchanged.
Earlier never-dispatched and compiler-failed attempts remain failures with their
own identities; “zero retries” above describes this successful run only. The
release uncertainty reported during the PR54 handoff is historical, not the
current terminal state of this completed run.

Only sanitized results and digests are published here. The manifest, receipts,
raw logs, private paths, credentials, training data and checkpoint weights remain
local; the hashes are provenance references, not public artifact downloads.

## What this closes and what remains

This closes actual local baseline training, checkpoint production, independent
fixed evaluation and terminal resource custody for the pinned profile. It does
not certify the complete production product. The following priorities reconcile
[the implementation closure map](IMPLEMENTATION_CLOSURE_MAP.md),
[original scope](V03_SCOPE_RECONCILIATION.md) and
[requirement audit](V03_FINAL_REQUIREMENT_AUDIT.md); implemented mechanisms are not
being reclassified as missing code.

| Priority | Unclosed original-plan acceptance | Existing foundation and next evidence |
|---|---|---|
| 1 | Governed real baseline/candidate comparison and real-target recovery | Candidate/change contracts, comparison workflow and local adapter already exist. A separately scoped reviewed candidate must use the frozen baseline/data/evaluator and independent evaluation; prove original-identity interruption/cancel/restart and release on the real target. A worse or inconclusive candidate is a valid comparison outcome; improvement is not required to pass faithful comparison acceptance. This baseline alone does not establish improvement or the whole failure matrix. No automatic optimization campaign is started or authorized by this record. |
| 2 | Real scientific-provider synthesis and domain acceptance | Source provenance, real PubMed retrieval and controlled synthesis already exist. Select the permitted scientific provider/question/source coverage; complete its exact usage/retry/pricing/input adapter contract and governed binding, then obtain domain review. Go coding subscription access is not a production scientific-provider selection. |
| 3 | Department workflow and production identity | Material assembly, separate review, Chinese UI and controlled login/native workflows already exist. Validate the selected real-material manager-to-user journey with department users; settle production temporary-plan policy and accept real IdP/TLS, subject/owner/reviewer mapping and revocation. Authorized demo development remains usable meanwhile. |
| 4 | Required existing remote receiver and Linux enforcement on actual hosts | Attachment, original-identity custody and controlled HTTP/process recovery are implemented. Accept real separate-host transport/TLS/authority, stop proof, and any selected delegated-cgroup enforcement with actual kernel/descendant evidence. Local GPU success does not certify multi-host operation or hostile-code isolation. Machine/cloud provisioning remains optional. |
| 5 | Target capacity and operations | Bounded load, admission, storage governance and PostgreSQL snapshot/restore tooling exist. Measure approximately 20 departmental users on the selected 32-core/64-GB or 54-core/192-GB host, sustained mixed workload and disk limits; establish monitoring and recovery/retention/RPO/RTO/PITR objectives and rehearse them. A single RTX 5070 run is not this acceptance. |

Single active scheduler remains the supported topology; multiple pollers and
optional scheduling/policy extensions are not automatically added to this scope.
The personal-agent/24-hour direction remains deferred as recorded in
[Draft PR51](https://github.com/Guanzhw/agent-factory/pull/51).
This documentation update starts no runtime feature, paid work, training loop,
merge or deployment.

The [PR54 toolchain handoff](RESEARCH_TOOLCHAIN_PATH_HANDOFF.md) remains the
source-only installation/reproduction procedure. Its prior UNKNOWN state is
retained as historical evidence; this record is the latest outcome. No rerun is
needed merely to record the milestone.
