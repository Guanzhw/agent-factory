# OpenResearch tool adapter

`platform/agent_factory/openresearch.py` implements a bounded CLI adapter for
the selected AgentOS runtime. It is **disabled by default and not registered as
a production tool**. Synthetic contract tests exercise OS subprocesses; live
literature retrieval and experiment execution remain unverified.

## Fixed source and binary admission

Required source: alphaXiv/OpenResearch
[`f336b121525d99364e2dee4fe90b2784894a54e6`](https://github.com/alphaXiv/OpenResearch/tree/f336b121525d99364e2dee4fe90b2784894a54e6).
Its [Cargo package](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/Cargo.toml)
declares version `0.2.13`. An operator must supply an approved `BinaryPin`
mapping that revision to the deployed binary's SHA-256. The adapter checks the
hash before every invocation and checks `orx --version` during each operation.
Matching version text alone does not establish source provenance. Unknown
mapping, changed bytes, missing binary, different revision/version, and disabled
configuration all reject admission. Keep the executable and pin immutable to
untrusted users; hash checks do not prevent an administrator replacing a file
between checking and execution. There is no installer or update operation.

On 2026-10-01, the development host's installed ORX reported `0.2.10` using an
isolated task-owned home with update notifications and telemetry disabled.
Only version/help were executed. That executable is not approved for this
integration and production remains disabled. No installed binary was changed.

## Supported boundary

Arguments are verified against the pinned
[CLI definitions](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/main.rs).
Each invocation also includes `--no-telemetry`. No shell interpolates arguments.

| Method | CLI arguments after executable and telemetry flag | Result |
| --- | --- | --- |
| `discover(query, corpus, limit)` | `discover keyword|openalex|biorxiv|pubmed QUERY --limit N` | Upstream JSON records, unchanged citation identity; N=1..200 |
| `paper(id)` | `paper ID` | Bounded raw output plus output hash |
| `paper(arxiv_id, full=True)` | `paper ID --source alphaxiv --full` | AlphaXiv extracted text; arXiv ID required |
| `experiment_status()` | `exp status EXPERIMENT` | Pinned human-output fields plus raw text/hash |
| `launch_experiment()` | `exp run EXPERIMENT --backend local` | Persisted launch intent and reconciled run state |
| `wait_experiment()` | `exp wait EXPERIMENT --timeout SECONDS --interval SECONDS` | Polls upstream store, then reconciles status |
| `cancel_experiment()` | `exp cancel EXPERIMENT`, followed by wait/status | Persisted cancellation request; terminal state only when observed |
| `run_logs()` | `logs RUN` | Only the authoritative run bound to this task |

Discovery JSON comes from the pinned
[retrieval implementation](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/commands/discover.rs).
Experiment status is human-readable, not a JSON API. The parser is restricted
to exact unique ID/command/latest-run fields in
[LocalPlane](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/plane/local_plane.rs).
It accepts starting/running/done/failed/cancelled and explicitly recognizes
never-run. Changed/ambiguous output blocks admission or stays UNKNOWN. A zero
exit from wait includes failed and cancelled; it does not establish success.
Captured output fixtures from an approved binary are still required before live
acceptance. Returned evidence is untrusted input to the agent.

## Ownership and effect control

Factory owns AgentOS sessions, the model loop, approval, task admission,
semantic request fingerprints, quotas, tool permissions and artifacts. The
adapter neither starts OpenCode/AgentOS services nor creates another agent
session. `agent spawn`, `exp wake`, `up`, `serve`, remote attachment, arbitrary
shell commands, login, installation, publication and managed compute are absent.
Remote runtime attachment is a separate platform boundary; this adapter's
experiment backend is explicitly local.

The core supplies a trusted absolute task scope and a current authorization
callback. Every command rechecks permissions. Cleanup uses the distinct
`experiment:cancel` operation; the core must authorize trusted reclaim even when
a previous owner's normal run permission has been revoked. Neither model text
nor frontend parameters may construct trusted `BinaryPin` or
`ExperimentBinding` values.

Experiment references require matching owner/task IDs, provisioned project and
experiment IDs, an opaque trusted connection reference, reviewed full source
commit and SHA-256 of the approved run command. Status verifies the run-command
hash before execution. The source commit is a reviewed binding attestation;
the CLI's abbreviated status commit is not proof of a full repository revision.
Each experiment/store is exclusive to one task. Other launchers must not modify
it. Bound local commands still need the platform's process/filesystem/network
isolation: an isolated HOME does not sandbox arbitrary experiment code.

Provisioning is deliberately outside this contract. The source offers
`create-experiment`, project view/edit and dashboard setup, but no general
`project create` CLI. A deployment must provision approved project/worktree
records **inside this task's ORX store**, review inherited commands, capture full
source/command provenance, and only then supply the binding. No shared user
store, production dataset, provider credential file or inherited model/session
environment is consulted.

The subprocess environment is built from a small OS allowlist rather than the
parent's credential-bearing environment. HOME, USERPROFILE, config/data/cache,
temporary paths, ORX_DATA_DIR and ORX_CACHE_DIR all resolve inside the task scope.
An operator may supply only absolute trusted PATH directories for required Git,
Bash and experiment executables. Update checks and interactive Git credential
prompts are disabled. Secrets must never appear in commands, prompts, catalog
materials, receipts or artifacts. Current adapter methods do not accept secret
environment bindings. See the pinned
[store resolution](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/store.rs)
and [Windows prerequisites](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/docs/windows.md).

## Unknown acknowledgements and cancellation

Before `exp run`, the adapter exclusively creates and fsyncs a task receipt with
UNKNOWN state and the previous run ID. Concurrent instances cannot both create
that intent. Repeated calls reconcile this intent and never submit a second
launch. A failed/lost acknowledgement before the effect stays UNKNOWN; after
the effect, a new authoritative run ID permits reconciliation. An unexpected
different run ID after binding requires manual reconciliation. Corrupt/partial
receipts fail closed. The caller must persist and retain the task scope across
restart; these receipts are not a replacement for the factory's durable ledger.
Their exclusive-file/fsync guarantees assume a supported local filesystem, not
arbitrary network mounts or whole-machine power-loss durability.

CLI output, duration and concurrency are bounded. Timeout/cancellation kills
the owned CLI process group (POSIX) or its process tree (Windows). This alone
does **not** reclaim a detached experiment. Native
[experiment cancellation](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/commands/exp.rs)
persists cancellation intent and starts/restarts the upstream supervisor. The
adapter invokes that operation and observes wait/status afterward. Cancellation
timeouts or missing terminal evidence retain UNKNOWN/running state and require
core reconciliation; do not free quota or claim cancellation merely because
the launcher exited. A core worker interrupted during launch must explicitly
reconcile/reclaim the retained binding on recovery.

## Verification and remaining acceptance

`platform/tests/test_openresearch_contract.py` launches clearly synthetic Python
CLI subprocess fixtures. It checks binary/version rejection, literal argument
handling, environment isolation, current revocation, output bounds, command
drift, one persisted launch intent, uncertain acknowledgements before/after an
effect, failure-vs-success wait semantics, process-tree termination, and detached
fixture cancellation/reconciliation. Synthetic pin hashes identify test scripts;
they are not approved ORX builds. Run with:

```powershell
$env:PYTHONPATH='platform'
python -m unittest discover -s platform/tests -p test_openresearch_contract.py
```

Live acceptance still requires an approved exact-revision binary/build manifest,
captured real output, provisioning and worktree/archive provenance, actual
no-cost retrieval/citation checks, approved experiment execution/evaluation,
supervisor hard-restart recovery/cancellation, model budget authorization and
tool registration in the plan-aware executor. No provider/model request, remote
compute or live research success is claimed by these tests.
