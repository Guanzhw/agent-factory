# Cloud Codex handoff checkpoint — WIP

This checkpoint preserves the actual-ORX/usage-ledger work on
`wip/orx-ledger-cloud-handoff`, based on verified commit
`6793a96c21be88f7145efc55a1312a06ab787628` (`feat/agno-factory`, draft PR #9).
It is **not acceptance complete**. Use the exact published checkpoint SHA from
the handoff response or `git rev-parse HEAD`; no merge or deployment is authorized.

## Write ownership

Local Factory development is frozen at publication of this checkpoint. Cloud
Codex is the next exclusive writer. Local agents must not edit, commit, push or
run new acceptance work after handoff without an explicit new assignment.
OpenSession remains local and is outside this migration. Only this task's owned
test/demo services may be stopped; other projects and global configuration are
untouched. Do not copy local credentials, personal files, databases or caches.

## Preserved implementation and evidence

- Actual pinned ORX CLI local provisioning, inspect/run/wait/logs/cancel,
  four original sealed evaluator files, durable single launch intent,
  task/project/experiment/run/source/command/result provenance and artifacts.
- Registered native Agno no-provider workflow, administrator plan review,
  separate native launch confirmation, exact operator connection group and
  immutable task environment limits. Factory remains the orchestration owner.
- Durable token/currency-micro ledger with explicit immutable pricing,
  provider-attempt reservations, retries/streaming/unknown usage, ancestor/user
  ceilings, legacy migrations and authenticated remote allocation/settlement.
- React provenance, verified downloads and ledger views; an opt-in isolated
  Windows startup profile and `scripts/accept_orx_browser.py` are preserved.

Verified focused runs before freeze:

| Check | Result | Scope |
|---|---|---|
| Frontend lint/typecheck/tests/build | 51 tests pass | Final local checkpoint preparation |
| Official npm production dependency audit | 0 vulnerabilities | No paid provider |
| Ruff / Pyright | pass / 0 errors | Platform and scripts |
| Actual ORX adapter | 10 pass, 104.785 s | Real pinned Windows binary, including owned worker/supervisor interruption |
| Actual Factory ORX suite | 8/9 pass, 159.632 s | Success, evaluator failure, running cancel with Job 0, source/command drift; revocation failed |
| Durable ledger | 19 pass, 10.184 s | Real PostgreSQL, controlled providers and synthetic prices |
| New remote usage | 8 pass, 105.353 s | Actual HTTP, independent services/databases, crash/restart/unknown/child/rate drift |
| Legacy remote handoff | 23 pass, 73.865 s | Final explicit grant fixture corrections |
| Legacy remote child | 1 pass, 39.442 s | Shared source budget narrowing |
| Origin authority / receiver binding fixtures | 14 / 9 pass | Exact explicitly registered zero local test models |

Full local regression finished: 364 tests in 677.116 s, with 2 failures,
1 error and 19 explicit opt-in skips. The process loaded old test fixtures before
their fixes: the two failing legacy remote handoff cases subsequently passed in
the final 23-case run; the unpriced origin-authority fixture subsequently passed
in its final 14-case run. The complete suite was **not rerun** on final source.
Actual Windows ORX tests were separately opt-in and are not counted as complete
full-suite success. Final focused revocation recheck after recording capabilities
still **failed** (1 test, 54.789 s); the remaining root cause is unresolved.
The capability omission is a confirmed bug corrected for new launches, not a
proven complete repair. No further local functionality or long tests are planned.
These results are also recorded in VERIFICATION.md. Ignored local output logs are
not uploaded because raw logs may contain machine-specific paths. These focused
passes must not be promoted to complete milestone acceptance.

## Known blockers and next work

1. The initial Factory revocation failure was traced to a missing capabilities
   field in the persisted launch connection binding. This checkpoint adds the
   exact original capability list for **new** launches; no old binding/effect
   hash is rewritten. The focused recheck result is recorded at handoff.
2. Read-only review found a remaining resource-accounting gap: the tool's
   settlement path requires positive process-stop proof only for cancellation,
   while done/failed effects can become DONE without `allStopped=true`.
   Lifecycle/delegation facts then count DONE plus native terminal as stopped.
   Require positive kernel stop proof for every terminal ORX effect; add a real
   orphan/remaining-supervisor regression before certifying capacity release.
3. Remote ORX experiment restart cleanup reads the original source tool pin,
   whereas ordinary imported execution uses receiver-effective bindings.
   Bind reclaim to the historically admitted receiver-local pin/proof without
   requiring current execution rights. Remote real ORX execution is unverified
   and should remain disabled; the remote usage tests use controlled providers.
4. Actual Factory/native durable-queue hard-interruption recovery remains
   unimplemented as acceptance. Adapter-only hard-worker recovery is distinct.
5. `scripts/start_orx_local.py` and the real browser workflow are **unrun**.
   Verify startup/publication/resume, approvals/progress/repeated submission,
   cancel/positive stop, lost acknowledgement/offline recovery and result/source
   downloads with the preserved supported Playwright harness. Syntax/static
   checks are not browser evidence.
6. This ORX containment profile requires Windows. Linux cloud Codex can run
   portable/core/PostgreSQL checks, but cannot certify Windows Job Objects or
   this actual binary. Use an explicitly assigned Windows runner for those
   opt-in cases; do not bypass the platform guard or substitute a mock.

## Versions and cloud setup

Pinned runtime: Agno 3.1.0, FastAPI 0.142.2, Uvicorn 0.54.0, SQLAlchemy 2.1.1,
Psycopg 3.3.6, uv 0.12.1, Ruff 0.15.8, Pyright 1.1.408. CI uses Python 3.12,
Node 24 and PostgreSQL 17.11; local checks used Python 3.14.3 and Node 26.5.1.
React 19.1.1, Vite 7.3.6, Vitest 4.1.11 and TypeScript 5.9.2 are locked.
The prepared browser harness used installed Python Playwright 1.58.0 and Edge.

```sh
git clone --branch wip/orx-ledger-cloud-handoff https://github.com/Guanzhw/agent-factory.git
cd agent-factory
git rev-parse HEAD  # compare to the exact handoff SHA before writing
npm ci --ignore-scripts
uv sync --frozen
npm run check
npm audit --omit=dev --registry=https://registry.npmjs.org
uv run ruff check platform scripts
uv run pyright
uv run python -m unittest discover -s platform/tests -v
```

PostgreSQL integration is opt-in. Supply a disposable **loopback** server URL in
`FACTORY_TEST_DATABASE_URL`, with permission to create generated test databases.
Each fixture owns and removes only its randomly named database; it never clears
the supplied database. `FACTORY_TEST_PG_BIN` enables existing backup/restore
tests when pinned PostgreSQL binaries are installed. Never point these commands
at production or register real credentials. See CI configuration for its
synthetic disposable PostgreSQL service. Ordinary CI intentionally skips actual
Windows ORX tests without the explicit pins below.

## Actual ORX acquisition/build and hashes

Public source is [alphaXiv/OpenResearch at the exact revision](https://github.com/alphaXiv/OpenResearch/tree/f336b121525d99364e2dee4fe90b2784894a54e6).
The measured source ZIP is obtained from the [exact public revision archive](https://codeload.github.com/alphaXiv/OpenResearch/zip/f336b121525d99364e2dee4fe90b2784894a54e6),
not a moving release. See [build provenance](ORX_BUILD_PROVENANCE.json).

- Revision: `f336b121525d99364e2dee4fe90b2784894a54e6`, CLI 0.2.13.
- Source ZIP: 7,317,108 bytes; SHA-256
  `396ef8731e8531f676171640e04b05848c00cb23c9647ccd6cadbcbda9f9a62a`.
- Build: Rust/Cargo 1.93.1, target `x86_64-pc-windows-msvc`,
  `cargo build --locked --release --bin orx` with an installed MSVC build toolchain.
- Reviewed binary: 42,894,336 bytes; SHA-256
  `d602b1b184589b72d9ce68a119b8959ee595f46869e951f63309781e60b173e7`.
- Cargo.toml SHA-256:
  `e430beec668ed34b9c171bc814dfae90bd5362a0ab5c598b6cfdde00a1380dda`.
- Cargo.lock SHA-256:
  `5e9f1753089dcdba38ba9f750a0b8b4acc625d6e0f98e4f8f58927ede8719ee6`.

The local executable, ZIP, Rust/MSVC caches and machine configuration are not
uploaded. A rebuilt binary may differ: fail closed on a hash mismatch; do not
silently replace the approved pin or treat version text as build provenance.
Any new exact binary approval must be explicit and supported by reviewed build
evidence. The profile does not use dashboard project POST, starter warm-up or
model/API calls; GitHub synchronization is false.

Windows actual tests:

```powershell
$env:FACTORY_TEST_DATABASE_URL = '<authorized-disposable-loopback-postgresql-url>'
$env:FACTORY_ORX_BINARY = '<reviewed-absolute-orx.exe-path>'
$env:FACTORY_ORX_SOURCE_ARCHIVE = '<verified-exact-revision-source.zip-path>'
$env:FACTORY_ORX_GIT_BINARY = (Get-Command git.exe).Source
$env:FACTORY_ORX_SHA256 = 'd602b1b184589b72d9ce68a119b8959ee595f46869e951f63309781e60b173e7'
# FACTORY_ORX_PYTHON_BINARY optionally pins the absolute evaluator Python executable.
uv run python -m unittest discover -s platform/tests -p test_actual_orx_local.py -v
uv run python -m unittest discover -s platform/tests -p test_orx_experiment_factory.py -v
uv run python scripts/start_orx_local.py --help
```

The unrun startup script requires explicit `--isolated-demo`, loopback
`--database-url`, a **new** `--workspace`, reviewed `--binary`,
`--source-archive`, `--git-binary` and optionally `--python-binary`/`--port`.
It creates only its generated demo database, publishes through distinct native
review and preserves it for `--resume`. Optional `--fixture-file` contains only
generated local demo JWTs; keep it under an ignored private directory, never
commit/copy it across machines. To run the unverified browser harness install
Playwright 1.58.0 in a dedicated test environment, provision its supported
browser, then use `scripts/accept_orx_browser.py --fixture <private-generated-file>
--output <ignored-evidence-directory>`. Do not copy local global browser config.

## Rebuildable task data and production boundary

All new recipe/dataset/sample identities and test task inputs are synthetic.
Fresh generated databases, owner connection references, native jobs, task homes,
ORX projects/experiments/runs and result artifacts can be reconstructed from
source and the pinned toolchain. Their IDs, run times and task-bound result hashes
will change; the sealed four-file recipe commit/archive remains deterministic:
commit `169b85d17a7faa5f15ca8bb5d7fe94ae1069b2d5`, archive SHA-256
`3feae56d2102a5d3ce9c1484747961013a0ab34003c450bcb201030c58460938`.
Toy baseline/candidate MSE is 16/0 over seven samples. Full dataset/evaluator/
command/result hashes travel in each actual result, not a chat completion claim.

No real credentials/user data/global configuration are needed or moved. Existing
local demo history and unrelated retained temporary directories stay local.
No paid provider, compute resource, new production access, merge or deployment
was performed. Job Objects enforce resources/process membership, not hostile
tenant filesystem/network/identity isolation. Production host identity/isolation,
live provider usage parsers and live model research remain outside acceptance.
