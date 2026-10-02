# Agent Factory

An original MIT departmental workspace over **Agno AgentOS 3.1.0 + PostgreSQL**. Managers maintain versioned materials and approved application definitions; users compose exact, scoped task plans and inspect native runs. Auto-Research is the first application. New approved applications use the same composition API and registered executor without application-ID branches in the core.

This is a **verified implementation stage toward the complete factory/v0.3 scope**: real authentication, PostgreSQL queue, questions, approvals, cancellation, events, artifacts and a Chinese research frontend. The deterministic model and invented research corpus are clearly labeled demo data. No paid model, production remote host or deployment is enabled. The opt-in Linux public-literature evidence workflow attempted a free PubMed query, but this host could not reach the endpoint; it produced an explicit failure report. Full production acceptance remains open.

## Start locally

Requires Node 24+, Python 3.12+, uv and existing PostgreSQL binaries. Tested locally on Windows with Python 3.14.3 and PostgreSQL 17.11. Dependency versions and CI action/image revisions are pinned.

```powershell
npm ci --ignore-scripts
uv sync --frozen
npm run check
npm run check:python
npm run build
# Existing PostgreSQL bin directory; this does not download/install PostgreSQL.
$env:FACTORY_POSTGRES_BIN = 'C:\path\to\postgresql\bin'
npm start
```

Open http://127.0.0.1:3100 and choose an explicit demo persona: Alice, Bob or material administrator. The demo script initializes only `.local/postgres`, binds both services to loopback and stops its owned services on Ctrl+C. Its trust authentication belongs only to the disposable local cluster. Do not expose the demo to a network. Logs, database, runtime files and credentials are ignored by Git.

For an operator-provided database, set `FACTORY_DATABASE_URL` and run `npm run start:configured`. The URL is server configuration, never agent input. Production mode (`FACTORY_MODE=production`) requires a configured JWT key, a separate clean database and native managed users/roles; it provisions no identities. Execution is checked per plan against exact approved applications, materials, installed adapters, owner connection pins and the configured approval policy. Missing items block that plan; there is no automatic demo-model fallback. Real provider SDK attempt/retry enforcement, production browser identity entry, reviewed mutable research workloads and production OS acceptance remain implementation/integration work; credentials alone do not complete them. The frontend dev command is `npm run dev:web`, proxying `/api` to loopback port 3100.

## Implemented boundary

- Six material kinds, immutable content versions/digests, author drafts, separate-administrator review, archive/withdrawal and inert structured import, pinned transitive dependency preflight and bounded approved-material discovery.
- Approved immutable application definitions, bounded goal-based discovery and proposal/revise/reject/accept, exact permitted material alternatives, and separate-administrator shared publication.
- Trusted registered model/tool/knowledge/environment factories selected by immutable material bindings; current owner connection references with bind/revoke, expiry, rotation and redacted metadata.
- Separate immutable plan, owner/task binding and Agno-owned job/session/ticket. User-scoped semantic fingerprints return 409 for changed duplicate requests.
- Native managed SQL authorization and fail-closed directory, scoped tool rechecks, owner-only jobs/artifacts, explicit demo identity with HttpOnly cookie.
- Native durable queue (two workers), questions and scoped confirmation, restart-tested snapshots, cancellation including bounded experiment process trees, persistent application events and artifact hashes.
- Bounded native child delegation: independent tickets, inherited scope, depth/count and durable shared tool budgets, group inspection and cascading cancellation.
- Guarded native schedule poller: owner-scoped immutable-plan definitions, per-occurrence admission, current rights/quotas, no blind UNKNOWN replay.
- Original research frontend: preflight, submission, polling, questions, approvals, cancellation acknowledgements, evidence and material manager. API facts bypass the model queue.
- Remote target/lease API and selected Agno HTTP adapter: trusted references, version/auth checks, UNKNOWN reconciliation, disconnect/cancel distinction and guarded reclaim. Actual native tests cover metadata attachment; lifecycle tests use explicit synthetic fixtures.
- Governed remote Factory execution: exact immutable receiver adapter/connection mapping proofs, current source authorization over trusted HTTP, separate receiver plan review and inherited receiver-owned children; default startup configures no remote access. See [remote bindings](docs/REMOTE_BINDINGS.md).
- Registered OpenResearch discovery and revision-2 paper/text/evidence tools: controlled transport is tested through native composition/queue/artifacts; actual public connectivity and model-driven research remain unverified. Operator registration, reviewed tool contract, owner connection and exact binary pin are required. Its pinned source is `f336b121525d99364e2dee4fe90b2784894a54e6` (ORX 0.2.13); an installed 0.2.10 is not assumed compatible. Factory retains session ownership.

Experiment metrics are computed by an actual bounded synthetic subprocess with evaluator/version/dataset/runtime hashes. They prove the integration pipeline, not scientific improvement. A native COMPLETED response alone never validates research or an uncertain effect.

## Checks

```powershell
npm run check
uv run ruff check platform scripts
uv run pyright
uv run python -m unittest discover -s platform/tests -v
# Disposable test DB only: enables actual native queue/API/PostgreSQL cases.
$env:FACTORY_TEST_DATABASE_URL = 'postgresql+psycopg://test-user@127.0.0.1:5432/disposable_test_db'
uv run python -m unittest discover -s platform/tests -v
```

Without a test database, PostgreSQL cases explicitly skip. The opt-in loopback test identity needs CREATEDB on a disposable server: each test class creates and removes only its own randomly named database; supplied database tables are never cleared. CI runs frontend and Python checks on Windows/Linux and a separate pinned PostgreSQL integration job. All tests use synthetic input and make no paid provider calls.

The opt-in actual ORX application and its reviewed evaluator are described in [ORX_LOCAL_EXPERIMENTS.md](docs/ORX_LOCAL_EXPERIMENTS.md). Its deterministic baseline/candidate MSE values are 16 and 0 on seven original examples. This verifies real local CLI execution and evidence delivery; it does not certify live model science. [TOKEN_LEDGER.md](docs/TOKEN_LEDGER.md) describes immutable model/price approval and transactional reservations for every provider attempt, including retries, streaming, child tasks and remote allocation. Defaults install only explicit no-provider local contracts; unpriced models fail closed.

See [architecture decision](docs/decisions/0001-native-plan-envelope.md), [architecture](docs/ARCHITECTURE.md), [security](docs/SECURITY.md), [delegation](docs/DELEGATION.md), [scheduling](docs/SCHEDULING.md), [remote resources](docs/REMOTE_RESOURCES.md), [OpenResearch](docs/OPENRESEARCH.md), [acceptance](docs/ACCEPTANCE.md) and [verification](docs/VERIFICATION.md).

## Current acceptance and remaining work

The [current acceptance matrix](docs/ACCEPTANCE.md#current-matrix) is authoritative;
older stage records and [the original handoff](docs/CLOUD_HANDOFF.md) remain history.
Actual Linux ORX toy execution, durable control receipts, scoped storage
retention, finite twenty-user pressure and online PostgreSQL snapshot/restore have
separate measured evidence on a **4-CPU/16-GiB** cloud cgroup. They do not certify
the target 32-core/64-GB or 54-core/192-GB hosts, hostile-code tenancy, PITR or
unbounded fair admission.

[Public literature evidence](docs/LITERATURE_EVIDENCE.md) adds bounded Linux
retrieval, paper/text tools and downloadable bibliography/excerpt reports with
explicit missing-full-text states. The controlled native path passes; actual
public retrieval is blocked by endpoint connectivity and is not scientific
acceptance. Experiment adapter revision 2 uses separate least-capability read
and compute connection pins; revision 1 remains available without rewriting old
plans, receipts or receiver guards.

Remaining code/integration includes real provider SDK usage/retry guards,
production browser identity entry and mutable reviewed research workloads.
[AT10 recovery](docs/INFERENCE_RECOVERY.md) now has a bounded standalone Linux
ORX v2 contract; provider, Windows and delegated/receiver recovery remain separate
integration and acceptance work. Production TLS/identity/host authorization,
target-host load and multiple-scheduler-replica behavior also need acceptance.
Twenty users does not imply twenty concurrent workers.

Plan approval is configurable with a conservative production administrator-review default. The real UI supports review requests and administrative decisions; see [plan policy and tested boundaries](docs/PLAN_POLICY.md). Live identity/model/ORX acceptance remains separate.

Trusted execution location selection and receiver-owned task trees are described in
[REMOTE_HANDOFF](docs/REMOTE_HANDOFF.md). No remote target is enabled by default.
Guarded hard-process schedule recovery and its native lease-release limitation are
recorded in [SCHEDULING](docs/SCHEDULING.md). Exact-source ORX build/preflight is
recorded separately from unverified live research.

Material-driven composition, adapter registration and compatibility rules are described in [MATERIAL_ASSEMBLY.md](docs/MATERIAL_ASSEMBLY.md). The default CLI installs only explicit demo adapters and safe native primitives. Real integrations require trusted same-process `Settings.runtime_adapters` and `Settings.trusted_connections`; these cannot be installed over HTTP. Enabling `FACTORY_RUNTIME_TOOL_CONTRACT=registered-runtime-v1` also requires new `FACTORY_POLICY_REVISION` and `FACTORY_MATERIAL_POLICY_REVISION` values. Preserve existing v1 policy hashes. Older demo plans need explicit exact `ApplicationService.adopt_legacy_demo_plan` proof before execution; startup does not silently adopt them.

Versioned publication/import and current material guards are described in
[material governance](docs/MATERIAL_GOVERNANCE.md). History pagination is documented
in [event replay](docs/EVENT_REPLAY.md). Actual twenty-user admission and clean-stop
PostgreSQL backup/restore evidence are in [operations](docs/OPERATIONS.md).

[Background lifecycle cleanup](docs/LIFECYCLE.md) observes current authority and descendant stop evidence without requiring the research page to poll.
