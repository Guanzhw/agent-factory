# Actual task-owned ORX local experiments

The first executable ORX application runs an original deterministic toy evaluator
through the pinned **real** OpenResearch CLI. Factory/Agno owns orchestration,
authority, approval and cancellation. ORX owns local experiment/run records and
detached experiment supervision. This is a no-model local experiment acceptance
fixture, not evidence of live model research or autonomous scientific discovery.

## Pin and startup failure diagnosis

The exact upstream commit is
[`f336b121525d99364e2dee4fe90b2784894a54e6`](https://github.com/alphaXiv/OpenResearch/tree/f336b121525d99364e2dee4fe90b2784894a54e6),
package `openresearch-cli 0.2.13`. The approved Windows binary SHA-256 is
`d602b1b184589b72d9ce68a119b8959ee595f46869e951f63309781e60b173e7`.
The freshly measured full upstream source archive SHA-256 is
`396ef8731e8531f676171640e04b05848c00cb23c9647ccd6cadbcbda9f9a62a`.
Version output alone does not establish source provenance. Both hashes must
match, and the source archive is read only, never exported as a task result.

The earlier real `exp status nonexistent` timeout was a Windows error-path
failure, not slow research. The pinned `src/main.rs:1005–1040` tests console
ownership and invokes blocking `MessageBoxW` on a command error. With
`CREATE_NO_WINDOW`, process-window enumeration positively found the command's
`OpenResearch stopped` dialog (class `#32770`), and the command exceeded four
seconds. With `DETACHED_PROCESS`, the identical binary returned its local
not-found error and exit code 1 in approximately 16 milliseconds. The adapter
uses a detached console; an actual regression test requires this error to return
within two seconds. No timeout expansion or mock hides this cause.

Actual long-running local launches also exposed inherited Windows stdout/stderr
handles: detached descendants can keep launcher pipes open after the real CLI
has exited. Task-local commands capture to bounded private files and await the
actual CLI process exit, separately tracking the detached process job. The
launcher acknowledgement is independent of a completed experiment and positive
stop evidence. SQLite read/provision connections close explicitly; their
transaction context alone would otherwise retain Windows file handles.

## Narrow local provisioning

`TaskLocalORXProvider` is an operator-owned handle installed on a trusted scoped
connection. User/model inputs select one of three fixed reviewed scenarios:
`success`, `evaluator_failure`, or `long_running`. They supply no commands,
executable paths, project paths, Git URLs, credentials, or compute backends.

A new canonical Factory task exclusively owns its home/config/cache/temp,
SQLite store and Git repository. A manifest is admitted exclusively before
provisioning. Existing unrelated stores/repositories cannot be attached. The
real `orx projects` command initializes the exact native schema. The narrow
provisioner verifies SQLite schema version 1, exact reviewed project/experiment/
run column shape, and absence of triggers, then inserts only the new local
project registration. It reproduces the fixed upstream
[`create_project`](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/local/projects.rs#L168)
semantics with empty GitHub owner/repository and **GitHub synchronization false**.
It creates no experiments, runs, agent sessions, warm-up jobs or results.

The actual `create-experiment` CLI creates the sole experiment. Actual
`exp run --backend local`, `exp status`, `exp wait`, `logs`, and `exp cancel`
create and observe authoritative run state. Factory reads this task-exclusive
SQLite store for complete identity, backend and source evidence; it never
inserts, edits or fabricates experiment/run status rows. The dashboard project
POST is unused: its starter warm-up can invoke installed coding agents, and
`--no-agent` is a no-op in this revision. No `up`, agent spawn, wake, login,
remote/cloud backend, model SDK call or provider credential is involved.

Interrupted project registration retains `PROVISION_UNKNOWN` if no safe
idempotent phase can be established. It does not start a replacement project.
After successful registration, the adapter can recover the single CLI-created
experiment from the private store after a missing creation acknowledgement.

## Reviewed experiment and evidence

The repository has exactly four original files: `baseline.py`, `candidate.py`,
`dataset.json`, and `evaluator.py`. The seven examples follow `y = 2x + 1` for
integer `x` from -3 through 3. The constant baseline predicts 1; the candidate
predicts `2x + 1`. Both are evaluated in the same actual executable experiment.
The expected mean squared errors are 16 and 0 respectively, an improvement of
16. These results are deliberately elementary and are not a research claim.

The deterministic Git commit uses a synthetic fixed identity/date. A complete
40-character recipe commit, exact `git archive --format=tar` SHA-256, approved
command SHA-256, upstream commit/archive hash, binary hash, task/project/
experiment/run identity, scenario and original file hashes accompany results.
The evaluator writes task/owner-bound JSON and both metrics before its reviewed
failure scenario exits 3. Factory verifies the actual extracted snapshot files,
the archive and result bytes, the native run commit/command and the original
manifest. A source/command/toolchain change rejects execution. Export accepts
only those four committed files; the downloadable recipe archive contains no
upstream source archive, private configuration or operator paths.

## Durable launch and recovery

The launch intent is exclusive and persisted/fsynced **before** `exp run`.
Factory tool-effect admission independently persists before invocation. The
exclusive task can have at most one native run. A missing acknowledgement leaves
UNKNOWN; reattachment inspects that original native run and never automatically
submits another launch. A present intent with no observed run also remains
UNKNOWN. Changed native run identity fails closed.

Windows named Job Objects are established before the CLI resumes from its
suspended state. Detached ORX supervisors and the native local-run nested job
remain within the outer task job. The job handle is inherited/retained, and
there is no kill-on-close setting: a Factory worker's hard exit retains the
original experiment for recovery. An actual test hard-exits the owning Factory
worker with `os._exit(31)`, reopens the same task, observes active detached
processes, reconciles the original run and cancels it without a duplicate.
Another actual test terminates only the identified task-owned supervisor,
confirms the evaluator remains active, and recovers via native cancel.

Cancellation first invokes the real native cancel command, which records intent
and can replace a crashed supervisor. Stop confirmation requires both native
terminal state and `QueryInformationJobObject` active-process count **zero**.
A launcher exit or missing PID is insufficient. A held job can forcibly reclaim
an orphaned tree if native cancellation cannot establish completion; in that
case Factory retains UNKNOWN/native-status-pending and reports scoped stop
separately, without fabricating an ORX cancelled row.

A cleanup-only handle requires the existing manifest and original exact limits;
it creates no directories or project and cannot provision/launch. Trusted core
reclaim remains available after ordinary tool authority is revoked or source/
command drift denies execution. It cannot enlarge authority or release results.

## Applied constraints and remaining isolation limits

This selected local profile requires Windows Job Objects. Unsupported platforms
or profiles are rejected before experiment launch. It accepts 5–30 seconds wall
time, 8 KiB–1 MiB output, 256 MiB–1 GiB aggregate memory, exactly eight processes,
and 1–100 percent CPU. Eight includes transient native CLI/bash/tar/evaluator/
supervisor processes; a four-process generic environment is refused.

Kernel job configuration and read-back enforce aggregate job memory, aggregate
CPU time, hard CPU-rate cap and active-process count. No breakaway or silent
breakaway option is enabled. The original evaluator independently enforces its
wall/output bound and starts no child processes. CLI capture, result and native
logs are bounded; the Factory tool layer maintains current plan/environment and
cancellation checks. Provider variables, proxies, SSH agents and user config
paths are not inherited; task-local home/config/data references are supplied.

These controls do not establish tenant security under a shared Windows account:
Job Objects are resource/process containment, not a filesystem/network/identity
sandbox. Same-account code can inspect/tamper with task files or other same-user
processes. Network access is not OS-denied by this profile, although the fixed
reviewed evaluator has no network/provider code. Arbitrary imported code,
untrusted evaluators and paid/remote compute are not supported. Production
requires separately reviewed OS identity, ACL/container/network isolation,
credential storage and restart supervision. No such access or deployment is
provisioned by this milestone.

## Verification

`platform/tests/test_actual_orx_local.py` is opt-in and invokes the actual pinned
Windows binary. Configure `FACTORY_ORX_BINARY`, `FACTORY_ORX_SHA256`,
`FACTORY_ORX_SOURCE_ARCHIVE`, and `FACTORY_ORX_GIT_BINARY` to operator-approved
absolute paths; Python uses the current interpreter's real base executable.
Run `python -m unittest discover -s platform/tests -p test_actual_orx_local.py -v`
with `PYTHONPATH=platform` from the project environment.

The actual acceptance suite covers prompt error return, successful metrics and
logs, evaluator failure, running cancellation with positive whole-job stop,
committed launch with lost acknowledgement, supervisor hard exit, current
revocation plus source drift with retained trusted cleanup, command/wrong-owner
rejection, unsupported constraints/upstream archive drift, and Factory worker
hard exit followed by one-run recovery. Deterministic fixtures in other suites
remain labeled as fixtures. A successful adapter suite alone is not proof of
Factory HTTP/browser integration; those checks are reported separately.

Local adapter acceptance: **10 actual-binary tests passed in 104.785 seconds**.
A final source-pin/stop-evidence success check passed in 12.232 seconds.
The existing bounded adapter contract suite passed **15 tests in 12.473 seconds**.
Ruff and Pyright passed for the changed adapter/containment modules.
These are local checks; exact-commit CI and Factory/browser evidence are tracked
in the project verification report.
