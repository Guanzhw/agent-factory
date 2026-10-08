# Controlled baseline/candidate workflow

The existing material/application governance, composition proposal, immutable
plan review, instance admission and native Agno task execute a single paired
comparison. The selected application is `controlled-comparison-fixture-v1`.
It is explicitly a development fixture with synthetic data, not a validated
scientific experiment or a general code execution service.

## Reviewed scope and execution

An operator installs exact runtime adapters and fixed process targets; ordinary
API requests cannot supply an executable, command, path, URL, environment,
dataset bytes, evaluator code or dynamic import. Six material kinds per mode
go through separate publication review, followed by separate application review.
The owner selects an exact published application version and finite mode in the
comparison workspace, then uses the existing proposal and plan approval flow.
No publication, connection registration or execution occurs on selection.

The baseline is a constant predictor over seven original synthetic samples.
The selected candidate is one of five installed configurations: linear, constant,
offset, explicitly failed evaluation, or bounded long-running cancellation
fixture. Only `predictor.json` changes. Dataset, evaluator, ordered sample set,
metric, direction, threshold and seed remain identical. Paths are inert labels;
the trusted evaluator and fixed inputs are embedded in a pinned ProcessSpec.

The plan includes the exact input manifest in a hashed knowledge material, the
mode and the executable adapter bindings. After plan admission, the existing
offline comparison contract is deterministically derived using that final plan
fingerprint and material references. The derived hash is not inserted back into
the plan, avoiding a circular self-hash or placeholder authority identity.

One native task, one original run and one existing `bounded_process_run` effect
execute the approved pair in a single process. Internal arithmetic is part of
that one effect, not two independently dispatched jobs. Existing shared-pool
admission, current permissions, leases, durable process intent, cancellation,
positive stop proof and release remain authoritative. The comparison service
does not launch or schedule anything. A lost launch acknowledgement only inspects
the original custody; UNKNOWN retains capacity and cannot authorize replacement.

The fixed process uses Python isolated mode with no site imports. CPU, address
space and file-size rlimits plus the existing cooperative process-group wall
guardian provide bounded controlled execution. These are not aggregate quotas,
network isolation or a hostile-code sandbox. No arbitrary untrusted code runs.

## Evidence and failure semantics

Only COMPLETED, exit-zero, positively stopped and released original custody may
provide output. Reading uses pinned root/directory identities, descriptor-relative
no-follow file access, regular-file/link/mode/size checks and bounded reads. It
does not accept a path from the model or API. Original process receipt identity
must match the owner, task, plan, native run and lease.

The parser validates actual output bytes against the fixed evaluator protocol,
complete ordered sample set, input hashes, choice and finite metric values. The
known deterministic calculation is a validation oracle, never a substitute for
missing output. Raw output and the derived report become existing task artifacts
under one `comparison-report-v1` effect. Each write and DONE transition checks
current authority and cancellation, including cancellation of a coroutine while
its file-reading thread is waiting. Partial writes leave UNKNOWN, never replay.

Historical reads validate the original process mapping, artifact bytes and
hashes, effect DONE, exact plan/input identities, both observations and the full
derived report. A native completed flag alone does not establish a comparison.
Owner checks precede private reads. The frontend verifies owner/task/plan scope,
matching common input pins and both result hashes against the raw artifact.

The controlled candidate-failure mode exits zero from the wrapper because it
successfully records an evaluator failure; the candidate observation is failed
with a null metric and the assessment is inconclusive. It never counts as an
improvement. Actual process failure, limit stop, cancellation, missing evidence,
tampering and UNKNOWN cannot produce a ranked result. Native task state, process
stop/release, evaluator outcome and scientific validity remain separate.

The pure `compare_observations` result retains `executionVerified: false` because
it evaluates supplied records only. The outer native evidence may set its own
execution verification after the complete custody/artifact checks above.
`scientificConclusionVerified` is always false at both layers.

## Acceptance and deliberately bounded interfaces

Actual Linux process/PostgreSQL tests cover original identity, output artifacts,
owner isolation, idempotency, tampering, candidate failure, cancellation, current
permission withdrawal before launch and report, lost acknowledgement and UNKNOWN
without replay. Pure tests cover scope/parser and thread-cancellation boundaries.
Desktop/mobile acceptance uses mock HTTPS login, a separate plan reviewer, the
real native runtime and task artifact downloads. The draft PR records final
counts, screenshots and exact-head CI; test definitions alone are not acceptance.

This stage implements only installed finite paired configurations. It does not
approve a real research question, private dataset, user-authored executable,
scientific metric, experiment validity, statistical significance or production
provider. Supporting a selected real experiment requires explicit reviewed
inputs and an appropriate adapter, rather than opening this fixture to arbitrary
code. See [IMPLEMENTATION_CLOSURE_MAP.md](IMPLEMENTATION_CLOSURE_MAP.md).
