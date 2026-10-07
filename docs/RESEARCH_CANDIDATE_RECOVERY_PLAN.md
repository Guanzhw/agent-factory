# One candidate and bounded target recovery: reviewable next step

Status: **preparation ready; GPU launch not ready**. This is a source-audited
handoff for parent review, not an execution authorization or automatic campaign.
No GPU job, credentials, billing, deployment or runtime feature is added here.
The [accepted baseline](RESEARCH_BASELINE_ACCEPTANCE.md) remains complete.

## Existing support and actual gaps

Audit base: documentation commit `c0db26c088a2f6ae4f649c501879af902296fcac`,
PR54 runner `df2c40bfe4993db722592264c26b8842178f48b4`, sealed PR50 package
`997013114a8c533c84078d174b220e541ea19f9a`.

| Boundary | Existing code / evidence | What must not be inferred |
|---|---|---|
| Candidate source | `research_candidate.validate_candidate_files`, `research_training_adapter.build_training_bundle` validate actual bytes, protected files and 11 allowed literal hyperparameters | Arbitrary train.py edits are not supported; DEVICE_BATCH_SIZE is overridden by approved microbatch and is unsuitable as the only candidate change |
| Candidate execution | `research_local_driver.build_local_driver` accepts `train_candidate.py`; `derive_local_identities` keeps baseline/evaluator independent of candidate; runtime registrations/settings/publication accept `variant_sha256` | These low-level APIs are not a candidate CLI |
| Native orchestration | `research_bootstrap_controller.run` uses existing proposal/review/task/lease/receipt paths; bootstrap and PR54 runner operate preparation → baseline → evaluation | Runner config is closed; `execute` selects `train_baseline.py`, and `research_bootstrap_assembly.research_application` supplies upstream twice and baseline variant. No candidate flag/path is exposed. Editing an upstream file or inventing a CLI option cannot select a candidate |
| Evaluation/comparison | Independent checkpoint/evaluator custody, `ResearchEvaluationService.verify`, `research_assessment.assess_observations`; controlled paired-comparison product flow already exists | The public score alone is not an authenticated observation; fixture comparison is not this real GPU comparison; advice never promotes code |
| Recovery | Original journal reopening; current owner checks; stop-only `observe_lease`; controller exception cleanup before lifespan closes; lost-ACK service reconstruction test forbids another launch | Existing-workspace CLI only emits `RESEARCH_BASELINE_EXISTING_INSPECT_ONLY`. It does not reconstruct a controller/service, resume evaluation or resume training |
| Process limits | Live guardian enforces cooperative limits; original positive stop/device evidence permits release | Killing guardian, rebooting the OS or missing stop proof can leave UNKNOWN/held. Model-only checkpoint has no optimizer/step resume; training accepts no initial checkpoint |

No new defect was reproduced in these existing contracts. Two operating-support
gaps are established: a reviewed candidate orchestrator, and a documented
original-service reconstruction/controlled-interruption harness for the chosen
recovery scope. These are cloud-completable work within the original project,
not department credentials or a reason to rebuild the material library. This
handoff supplies executable offline preparation and existing recovery smokes;
it deliberately supplies **no fictional GPU candidate/resume command**.

## Proposed scientific comparison, exactly one candidate

For review, change only the pinned upstream literal `MATRIX_LR = 0.04` to
`MATRIX_LR = 0.036`. This 10% learning-rate reduction is an infrastructure
comparison candidate, not a predicted improvement or search campaign. The actual
pinned file was inspected and this exact edit passed the existing adapter.
Candidate train.py SHA256:
`5c4cd6836ce5eb1be7657abaad430bc9910292512bc3184f1c41b32d635138bf`.

Keep all other source bytes and generated architecture/data/evaluator fixed:
upstream `228791fb499afffb54b46200aca536f79142f117`, RTX5070/SM120,
SDPA, microbatch1, TOTAL_BATCH_SIZE `2**19`, seed42, sequence2048,
300 counted training seconds after the source's 11 warmup steps, and original
20,971,520-token evaluation protocol. Coverage evidence remains fixed source
plus independent evaluator custody, not an added independent token counter.

Reuse the accepted **baseline observation** from the original verified
`evaluation-receipt.json` → `imported.observation` and original training config's
`comparisonManifest`. Do not type the published score into a new observation.
Reuse its checkpoint as retained evidence, **not as candidate initialization**;
this profile trains each variant from scratch with `initialCheckpoint: null`.
No automatic baseline rerun is needed when the complete comparison identity
matches. If it does not match, stop and report the exact differing field.

The full manifest includes installed inventory, device, evaluator, data/tokenizer,
seed, wall bound and artifact limits. Matching just data and score is insufficient.
Keep the accepted project/venv and sealed package unchanged. A package reinstall,
watchdog increase or inventory change can invalidate comparability. An external
operator harness using existing APIs can preserve the installation; an in-place
package edit cannot. Fresh workspace/cache/preparation bindings are allowed only
when actual manifest fingerprint equality survives the existing capture checks.

### Executable offline candidate preparation, no GPU

Use the already accepted Python and pinned upstream directory. `CANDIDATE_REVIEW`
is a fresh absent private directory, separate from every old attempt and sealed
installation. `UPSTREAM` contains the six original pinned public source files.
This command parses/hashes but never imports or executes upstream/generated code,
opens the database or imports Torch. The generated candidate is a review input,
not a staged executable. Use `set -euo pipefail` in the shell session.

```sh
"$ACCEPTED_PYTHON" -I -B - "$UPSTREAM" "$CANDIDATE_REVIEW" <<'PY'
import hashlib, json, os, sys
from pathlib import Path
from agent_factory.research_profile import SOURCE_SHA256, verify_upstream_source
from agent_factory.research_training_adapter import build_training_bundle
from agent_factory.research_local_driver import derive_local_identities
upstream_root, output = map(Path, sys.argv[1:])
assert upstream_root.is_absolute() and output.is_absolute()
assert '..' not in output.parts and not output.exists() and not output.is_symlink()
upstream = {name: (upstream_root/name).read_bytes() for name in SOURCE_SHA256}
verify_upstream_source(upstream)
old, new = b'MATRIX_LR = 0.04', b'MATRIX_LR = 0.036'
assert upstream['train.py'].count(old) == 1
candidate = {**upstream, 'train.py': upstream['train.py'].replace(old, new, 1)}
assert hashlib.sha256(candidate['train.py']).hexdigest() == '5c4cd6836ce5eb1be7657abaad430bc9910292512bc3184f1c41b32d635138bf'
bundle = build_training_bundle(upstream, candidate, microbatch=1)
original = derive_local_identities(upstream, upstream, microbatch=1)
changed = derive_local_identities(upstream, candidate, microbatch=1)
for field in ('baseline', 'evaluatorCode', 'evaluatorConfiguration'):
    assert original['identities'][field] == changed['identities'][field]
assert bundle['generatedFiles']['train_candidate.py'] != bundle['generatedFiles']['train_baseline.py']
os.umask(0o077)
output.mkdir(mode=0o700)
for name, raw in candidate.items():
    with (output/name).open('xb') as stream:
        stream.write(raw)
receipt = {'schema': 1, 'status': 'OFFLINE_CANDIDATE_READY_NO_EXECUTION',
    'change': {'parameter': 'MATRIX_LR', 'before': 0.04, 'after': 0.036},
    'adaptationReceipt': changed['adaptationReceipt'],
    'derivedSha256': {key: value['sha256'] for key, value in changed['identities'].items()},
    'executionVerified': False}
with (output/'candidate-review.json').open('x') as stream:
    json.dump(receipt, stream, sort_keys=True, indent=2)
print('OFFLINE_CANDIDATE_READY_NO_EXECUTION')
PY
```

The existing source hash checks are reused, not replaced by new approval gates.
Retain a partial output directory if the command fails; do not repair an old
sealed root. Before eventual launch, compare the actual derived baseline and
manifest to the retained accepted records through existing driver/capture
validation. Offline readiness alone never authorizes launch.

## Resource/time envelope and required local values

Use the exact accepted private canonical config `limits` values without changes:
`cpu_seconds`, `address_space_mb`, `file_size_bytes`, `wall_seconds`, `disk_bytes`,
`output_bytes`. The public final handoff did not supply those numeric limits or
phase wall times; **900 seconds from an old example is not an approved limit**.
The local owner must carry these existing values into the review record; no new
credential or department input is needed. Let `L` be that original wall_seconds.

- One candidate training and one independent evaluation, serial, one GPU lease
  active at a time, zero retries and no automatic promotion. Each process retains
  wall bound `L`; existing controller bound is `min(86400, L + 120)` per stage.
- Keep the same CPU/memory/disk/log/checkpoint bounds and device exclusivity
  accounting. This does not claim physical GPU isolation from outside processes.
- Retain the accepted 159392448-byte baseline checkpoint. The candidate must fit
  the original checkpoint limit; do not shrink or grow that bound to obtain PASS.
  Local free space must cover the fresh stage roots/caches/checkpoint under the
  existing disk policy while preserving all old artifacts.
- Preparation keeps its existing 5-second process bound and input capture's
  120-second cooperative bound. Controller/DB setup and synchronous cleanup have
  their existing I/O timeouts; `2*(L+120)` is **not** a proven whole-command bound.
  Record compilation, warmup, counted training, evaluation and total elapsed
  separately. If the unchanged envelope proves insufficient, stop; do not extend
  it mid-run or silently compare a changed manifest.
- Recovery smoke is separate from the scientific candidate. A subsequent actual
  GPU interruption lane, if included in the parent's reviewed scope, is at most
  one additional fresh attempt with the same or lower approved resource envelope,
  no evaluation/score and no retry. It is not a second candidate search.

## Executable target cooperative recovery smoke, no GPU

Use the reviewed source checkout's runtime and tests with an existing compatible
control interpreter/dependencies. The wrapper pins parent imports to that same
source used by the test child, avoiding mixed installed/source revisions. This
is reviewed-source smoke, not an installed-package identity audit. Do not install
test packages into the sealed research venv. The
PostgreSQL cases require an **already authorized disposable loopback fixture**
with its existing `FACTORY_TEST_DATABASE_URL`; never point them at the baseline
application database or production. If unavailable, record NOT_RUN and stop this
lane; do not provision credentials/databases merely to satisfy it. Each fixture
creates/drops its own random isolated test database under existing fixture rights.

Run serially. The wrapper treats any skip as NOT_ACCEPTED, never as PASS:

```sh
"$CONTROL_PYTHON" -I -B - "$REVIEWED_SOURCE/platform/tests" <<'PY'
import sys, unittest
from pathlib import Path
tests = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(tests), str(tests.parent)]
import agent_factory
assert Path(agent_factory.__file__).resolve().parent == tests.parent/'agent_factory'
names = [
 'test_process_enforcement.ProcessEnforcementTests.test_reopened_owner_can_cancel_original_without_dispatch',
 'test_research_bootstrap_controller_postgres.ResearchBootstrapControllerPostgresTests.test_failure_after_dispatch_stops_original_guardian_before_lifespan_closes',
 'test_research_local_postgres.ResearchLocalPostgresTests.test_lost_launch_ack_restart_recovers_only_original_process',
 'test_process_runtime_postgres.ProcessRuntimePostgresTests.test_running_pool_contention_and_current_cancel_stop_original_process',
]
result = unittest.TextTestRunner(verbosity=2, failfast=True).run(
    unittest.defaultTestLoader.loadTestsFromNames(names))
raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 2)
PY
```

These are real Linux child/native/PostgreSQL tests with synthetic programs and
mocked GPU observations. They establish original-journal reopen, lost-ACK
service-object reconstruction without relaunch, controlled exception cleanup
before lifespan closes, and busy-pool refusal. They do **not** establish a fresh
OS-process controller restart, a real GPU interruption or training continuation.
Do not describe mocked device RELEASED as real target GPU release.

## Concrete implementation handback before any GPU command

A separate bounded operator harness can reuse the installed driver, native
controller, preparation/checkpoint stores, observer and evaluation service. Keep
scientific execution-library and installation bytes unchanged. The minimum
reviewable wiring must:

1. Accept the one reviewed candidate byte map outside the sealed upstream root;
   validate it using the APIs above. Do not monkeypatch the baseline CLI or source.
2. Capture the same scientific manifest; select `train_candidate.py` and the
   derived **candidate** identity in driver, target registration, material
   publication and lease guard. The evaluator must also bind that candidate
   variant and original candidate checkpoint. Do not relabel a baseline task.
3. Reuse the existing native proposal/separate review/paused-task/controller flow,
   one allocation and one import per stage, new workspace/request identity, and
   explicit `PATH=/usr/bin:/bin` with existing credential filtering. Preserve
   earlier target registrations while original evidence is being resolved.
4. Load the retained baseline observation from its already verified receipt,
   obtain the candidate observation from `ResearchEvaluationService.verify`,
   check comparison identity equality, and call `assess_observations`. Keep its
   result advisory, including worse/tie/inconclusive; never mutate accepted code.
5. Supply an explicit recovery hook and persist the original identity set before
   interruption. The existing PROCESS_SUBMITTED event is allocation ACK, **not
   spawn/GPU-work proof**. For actual GPU interruption, first observe original
   guardian/child RUNNING and device evidence for that same process, then raise
   a controlled operator exception while the original lifespan remains alive.
   Existing cleanup may cancel/observe the original lease; do not kill guardian,
   child group, database or OS, or claim checkpoint-based training resumption.
6. If fresh-process controller restart is required instead of controlled
   exception/service reconstruction, first implement and test exact original
   service/target/spec rehydration. It is not supplied by the existing-workspace
   CLI; do not invent a resume command or change request IDs to recover.

This is an identified operating harness gap, not a reproduced defect demanding a
runtime patch. Parent review should choose the interruption definition and review
the concrete harness before local GPU execution. No department SSO is needed to
complete this wiring and deterministic tests. Reinstalling a changed runtime
would require a separate comparability decision, not automatic baseline reuse.

## Evidence and stopping criteria

Keep one private record per lane: exact source/runtime/adapter and candidate
hashes, scientific manifest equality, original task/native run/plan/lease/provider
IDs, actual attempt/allocation/launch counts, stage timing and resource bounds,
checkpoint digest/size, trusted evaluator contract and both observations,
advisory comparison, final journal/PostgreSQL/device/claim release chain.
For recovery additionally record injection point, original identities before/
after, no-relaunch assertion, original stop proof and retained ACK state.
Reuse normal receipts and the already verified baseline; no redundant historical
configuration audit or never-dispatched gate applies to executed jobs.

Stop immediately on source/manifest mismatch, busy admission, revoked authority,
unexpected second allocation/launch, unsupported stage/restart, nonfinite metric,
artifact mismatch, bound exhaustion, or absent positive stop/GPU release. A failed
candidate is inconclusive, not score zero; worse/tie is a valid measured outcome.
UNKNOWN preserves capacity and evidence and blocks subsequent GPU work. No ACK
replay, manifest rewriting, directory reset, automatic retry, budget increase or
cleanup by deleting historical artifacts. If the controlled interruption hook
cannot reach verified RUNNING within its existing bound, record NOT_EXERCISED;
absence of observed work is not interruption acceptance.

## Work now versus environment dependencies

Cloud-completable now: audit, exact candidate derivation, bounded harness design/
implementation and deterministic no-GPU tests. Existing accepted target owner
supplies retained manifest/receipt/config limits and later real device observations;
these are local research inputs, not department production inputs. A disposable
PG fixture is needed only for the native smoke tests, never a reason to reuse a
production DB. Department IdP/users/data, production scientific provider, real
multi-host deployment and 20-user target capacity are separate original-plan
acceptance and do not block this local candidate preparation. Personal-agent/
24-hour work remains deferred.

Cloud evidence for this handoff: the actual six pinned public upstream files
passed verification; the exact MATRIX_LR edit generated distinct candidate code
while baseline/evaluator identities remained unchanged. Thirty existing targeted
tests passed, including one real Linux journal-reopen/cancel process test. No
Torch or GPU ran. The two inline commands were parsed and exercised in cloud:
candidate preparation succeeded; the smoke wrapper ran its Linux process case,
explicitly skipped three unavailable PostgreSQL cases, and correctly exited 2.
Those skips are not acceptance. Target smoke and candidate/recovery GPU lanes
were not run.
