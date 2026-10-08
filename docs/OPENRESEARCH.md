# OpenResearch tool adapter

`platform/agent_factory/openresearch.py` implements a bounded CLI adapter for
the selected AgentOS runtime. A narrow `orx_discover` factory is registered by the core, but execution requires an explicitly reviewed runtime-tool contract, approved material/application, owner connection and trusted operator adapter provider. The default startup configures none of those live ORX handles. Synthetic contract tests exercise OS subprocesses; one actual bounded public OpenAlex discovery is verified below. Registered native integration uses labeled controlled transport. Real integrated model-driven literature tasks and ORX experiment execution remain unverified.

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
real integration through the now-registered plan-aware executor tool. No provider/model request, remote
compute or live research success is claimed by these tests.

## Exact-source native build checkpoint

A separate task-owned Windows build of the exact source revision succeeded with
`cargo build --locked --release --bin orx`, Rust/Cargo 1.93.1 and
`x86_64-pc-windows-msvc`. The installed 0.2.10 executable was left unchanged.
The isolated 0.2.13 executable is 42,894,336 bytes, SHA-256
`d602b1b184589b72d9ce68a119b8959ee595f46869e951f63309781e60b173e7`.
Source archive: 7,317,108 bytes, SHA-256
`396ef8731e8531f676171640e04b05848c00cb23c9647ccd6cadbcbda9f9a62a`.
Cargo.toml SHA-256: `e430beec668ed34b9c171bc814dfae90bd5362a0ab5c598b6cfdde00a1380dda`;
Cargo.lock SHA-256: `5e9f1753089dcdba38ba9f750a0b8b4acc625d6e0f98e4f8f58927ede8719ee6`.

The actual adapter version/hash preflight passed against this executable; a
wrong pin rejected before spawning. Version/help startup and unsupported-harness
allowlist rejection were checked with isolated homes and filtered provider
environment. No provider/research/session/server operation ran. A bounded
local-only status lookup for a nonexistent experiment timed out at 10 seconds;
cleanup ran, but its cause and successful real status parsing remain unverified.
There is no successful live project/experiment workflow evidence.

`platform/tests/test_actual_orx_preflight.py` is opt-in with an operator-supplied
`FACTORY_ORX_BINARY` and `FACTORY_ORX_SHA256`. It runs only version preflight and
wrong-pin rejection. Ordinary CI does not download/build/run ORX. This manifest
attests one local build, not reproducibility or production approval. Neither the
binary, build cache, isolated homes nor private build paths are published.

## Actual public metadata discovery

One bounded actual `OpenResearchAdapter.discover` call against the exact pinned
binary returned three OpenAlex records in 1.034 seconds. The adapter used a trusted
BinaryPin, task-owned isolated homes/store, current authorization callback,
15-second timeout and 64 KiB output cap. Its local version preflight preceded
the one retrieval operation. No credentials file, receipt/project state,
model/provider request or resource provisioning was involved. Adapter result JSON
SHA-256 was `4c9ad41210c88dfb9b5798258bd619791e43441badda5ff853d0720bcdcbdece`.

Pinned source implements this route as an unauthenticated public OpenAlex metadata
GET. A separate raw CLI diagnostic also succeeded; it is not substituted for the
Python adapter result. This proves that narrow retrieval path only. It does not
enable production registration, verify literature synthesis/scientific outcomes,
or resolve actual experiment/supervisor/isolation/model-budget acceptance.


## Registered native discovery stage

`orx_tools.py` installs `openresearch-discover-v1@1`, named `orx_discover`, with
the narrow `research:read` capability. Material config is inert. A trusted
`TaskORXAdapterProvider` connection handle constructs a task-scoped adapter;
HTTP accepts neither binaries, commands, paths, credentials nor provider code.
Current exact owner/task/connection pins are resolved before invocation and while
the owned operation runs. The adapter scope uses separate homes/config/cache and
workspace under the operator root; that path hygiene is not tenant security.

The command/output deadline is the minimum of operator, immutable plan and
selected trusted environment limits. Timeout/cancel/revocation cancels and awaits
the owned operation; uncertain results retain UNKNOWN effects and capacity.
CPU, memory and process-count containment for the real ORX CLI is **not** supplied
by this registered adapter. It must be provided and accepted by deployment
isolation before production research. Fixed synthetic experiments have their own
tested native process bounds; those do not certify ORX isolation.

One actual PostgreSQL/native test publishes exact tool/application definitions
through distinct reviewers, binds Alice's opaque connection, composes a plan and
runs the native queue to a durable DONE effect and hash-checked artifact. Its
adapter is explicitly `controlled_transport_fixture`: `configuredBinarySha256`
records the configured contract, not executed binary proof. Eight callable tests
cover replay, UNKNOWN, cancellation, current authority loss and resource failure.
They make no CLI, retrieval, provider/model or compute-provisioning request. Real
integrated cancellation and ORX experiment launch/status/cancel are not tested or
wired. ORX's own OpenCode/session spawn/wake paths remain omitted.

## Actual local experiment checkpoint (2026-10-02)

The earlier status timeout above was traced to the pinned Windows blocking error dialog and fixed with detached-console startup. Actual local experiments now have focused adapter and Factory evidence, separately recorded in [ORX_LOCAL_EXPERIMENTS.md](ORX_LOCAL_EXPERIMENTS.md). The cloud checkpoint remains WIP with known cleanup/recovery/browser gaps; [CLOUD_HANDOFF.md](CLOUD_HANDOFF.md) is authoritative for current acceptance limits. Live model research and production isolation remain unverified.
