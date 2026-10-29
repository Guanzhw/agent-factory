# Agent Factory

An original MIT departmental workspace over **Agno AgentOS 3.1.0 + PostgreSQL**. Department members create and publish versioned materials and application definitions, compose exact scoped task plans, and inspect native runs. Administrators manage accounts; resource owners control their own sharing, changes, withdrawal and archival. The default deployment contains no installed applications or seeded materials. Members publish explicit application definitions and use the generic composition API and registered executors.

The default core composition provides login, the application catalog, tasks and owner-managed resources without installing an application. Auto Research is available through the explicit research backend and browser composition described below; it has its own home and research workspace. A new core-only database starts with an empty application catalog. Synthetic native fixtures are installed explicitly by tests, never by default startup.

Runtime, browser and CI acceptance must be recorded against the exact revision and selected composition; Research results do not establish core-only acceptance. Real external identity providers, paid models, remote hosts and scientific workflows are not validated by local synthetic checks. Historical implementation and acceptance records remain linked below.

## Build a new application

Start with the [application development guide](docs/APPLICATION_DEVELOPMENT.md).
Use the [public application interface](docs/APPLICATION_INTERFACE.md) for scoped
inputs/resources, native step output, task lifecycle, events and artifacts.
It separates business implementation, trusted deployment registration and member publication,
and covers the smallest material-driven application, trusted tool/model/runtime
factories, bounded Pydantic inputs, native Agno Workflow/HITL, permissions, budgets
and executable checks. The [workflow governance reference](docs/GOVERNED_WORKFLOW_AGENTS.md)
explains original-operation custody and native continuation. Agno owns workflow
progress; Factory supplies governance and thin receipts. Real ConvertD remains a
user-implemented local application, not a bundled or live-validated backend.

## Source and deployment boundaries

The default source and deployment boundaries are:

| Path | Owns |
| --- | --- |
| `platform/agent_factory/` | Shared identity, credentials, resources, material/application contracts, task admission, native execution, events and artifacts |
| `deployment/agent_factory_server/main.py` | Core startup with an empty default application registration list |
| `web/composition.tsx` | Explicit frontend assembly; shared shell and generic UI remain in `web/` |

There is no dynamic application discovery. Applications that combine installed
adapters need published declarations and materials; new trusted code requires
explicit deployment registration. The Research application lives in
`applications/research`, with `deployment/agent_factory_server/research.py` and
`web/research-composition.tsx` as its explicit composition entrypoints. Selecting
the core-only composition does not delete stored applications, task history,
credentials, vault keys, artifacts or backups. Existing Research tasks require
their original application code to resume. Core-only checks use newly created
isolated fixtures; they do not remove old data.

The root [`pyproject.toml`](pyproject.toml) builds the
`department-agent-factory` deployment wheel, including the separately selected
`agent-factory` and `agent-factory-research` entrypoints.
[`platform/pyproject.toml`](platform/pyproject.toml) builds the standalone
`department-agent-factory-core` distribution, containing only `agent_factory`.
These are alternative distribution choices, not packages to overlay in one
installation. See the [development guide](docs/APPLICATION_DEVELOPMENT.md#源码归属与静态装配)
for assembly and source-checkout commands.

## Start with configured authentication

Requires Node 24+, Python 3.12+, uv and an existing operator-managed PostgreSQL database. Choose explicit local password login for function checks or the existing OIDC integration. There is no default account, demo login, bundled identity provider, disposable database launcher or offline research prototype.

For local password login, stop the service and supply `FACTORY_DATABASE_URL` and
`FACTORY_JWT_KEY` through your existing secure configuration. Set `FACTORY_TLS_CERT`
and `FACTORY_TLS_KEY` to your existing certificate/key paths; the certificate must
cover the chosen host and be trusted by the browser. Replace `your-new-member-id`
with a new member ID:

```sh
npm ci --ignore-scripts
uv sync --frozen
npm run build
uv run agent-factory-local-user your-new-member-id
# Enter and confirm the password at the hidden prompts, never in arguments or environment variables.
export FACTORY_LOCAL_LOGIN_ORIGIN=https://127.0.0.1:3100
uv run python -m uvicorn agent_factory_server.main:create_app --factory \
  --host 127.0.0.1 --port 3100 \
  --ssl-certfile "$FACTORY_TLS_CERT" --ssl-keyfile "$FACTORY_TLS_KEY" --no-access-log
```

The command creates only a new ordinary member and stores a salted password hash.
It rejects any existing native user or local credential; it does not attach a
password to an old identity, grant administrator status or reset passwords. A
failed or interrupted command is not success: it can leave a member without a
local credential, and must not be retried as an overwrite or followed by deleting
old data. Passwords are 12–128 characters and are not trimmed. Create each needed
account explicitly while the service is stopped.

Open `https://127.0.0.1:3100`, use the username/password form, and use the workspace
menu to sign out. The origin must exactly match `FACTORY_LOCAL_LOGIN_ORIGIN`;
HTTPS, Secure cookies and Origin/CSRF checks also apply on loopback. For the
explicit Research workspace, use `npm run build:research` instead of `npm run build`
and `agent_factory_server.research:create_app` in the same server command, then
enter AutoResearch from the application catalog. Login does not configure a model
or start research.

`npm start`, `npm run dev` and `npm run start:configured` retain the plain HTTP
server entrypoint; use the HTTPS command above or an already configured HTTPS
deployment for browser login. Missing signing configuration fails startup; with
neither local login nor browser OIDC configured, login remains unavailable. Old
demo-mode configuration is rejected. A previous demo database cannot be silently
used as a production database; keep it untouched pending a precise data inventory
and separate cleanup decision.

The separate OIDC browser entry uses an operator-constructed `Settings.browser_oidc=BrowserOIDCConfig(...)` with HTTPS issuer/endpoints, public-client ID, exact callback, pinned public keys and existing member mappings. See [the browser contract](docs/BROWSER_AUTH_PROCESS_ENFORCEMENT.md) and [upgrade instructions](docs/REMOVE_DEMO_UPGRADE.md). If both login methods are configured, their application origins must match; a failed login never falls back to the other method. This is trusted deployment composition, not an environment-based IdP setup wizard. A separate external bearer-token verifier is available through `Settings.oidc_identity`. Local password checks do not configure or certify an organization identity provider. The frontend-only `npm run dev:web` proxies `/api` to the configured local server and provides no identity bypass.

Normal entrypoints use core `Settings.from_env()` with
`member-self-service` for task admission and material/application publication.
Members publish their versions directly and submit new tasks without ordinary
plan approval. Native tool confirmations remain when declared by installed tools. Historical reviews stay readable and do not authorize new tasks.
Plans without explicit execution bindings must be regenerated. An unknown original outcome still
requires original-request reconciliation. Retired plan/publication modes and
review TTL settings must be removed from startup configuration.
See [department collaboration and migration](docs/department-minimal-integration.md).

The standalone core starts with `python -m agent_factory` after installing
`department-agent-factory-core`. It provides accounts, encrypted credentials,
models, remote services, CLI/MCP tools and SSH without the research application.
Normal startup creates a persistent 32-byte vault key at
`FACTORY_WORKSPACE/runtime/credential-vault.key` (workspace defaults to `.local`).
Back up this key with its PostgreSQL database and retain it across restarts;
restoring the database alone cannot decrypt credentials. Restrict filesystem
access to the service account. An injected organizational vault remains supported.

## Implemented boundary

- Six material kinds, immutable content versions/digests, member drafts and direct publication, author-managed archive/withdrawal, inert structured import, pinned transitive dependency preflight and bounded published-material discovery.
- Published immutable application definitions, bounded goal-based discovery and proposal/revise/reject/accept, exact permitted material alternatives, and member publication of new shared versions.
- Trusted registered model/tool/knowledge/environment factories selected by immutable material bindings; current owner connection references with bind/revoke, expiry, rotation and redacted metadata.
- Personal CLI/MCP adapters are installed statically; members register them with matching owner credentials and bind connections for on-demand calls ([setup and lifecycle](docs/PERSONAL_TOOL_CONNECTION_LIFECYCLE.md)).
- Separate immutable plan, owner/task binding and Agno-owned job/session/ticket. User-scoped semantic fingerprints return 409 for changed duplicate requests.
- Native managed SQL authorization and fail-closed directory, scoped tool rechecks, owner-only jobs/artifacts, explicitly configured local password or external identity with protected browser sessions.
- Native durable queue (two workers), questions and scoped confirmation, restart-tested snapshots, cancellation and bounded local process custody, persistent application events and artifact hashes.
- Bounded native child delegation: independent tickets, inherited scope, depth/count and durable shared tool budgets, group inspection and cascading cancellation.
- Guarded native schedule poller: owner-scoped immutable-plan definitions, per-occurrence admission, current rights/quotas, no blind UNKNOWN replay.
- Shared workspace: login/logout, empty application catalog, task history, owner models/connections, member material/application management and generic composition. API facts bypass the model queue.
- Remote target/lease API and selected Agno HTTP adapter: trusted references, version/auth checks, UNKNOWN reconciliation, disconnect/cancel distinction and guarded reclaim. Actual native tests cover metadata attachment; lifecycle tests use explicit synthetic fixtures.
- Governed remote Factory execution: exact immutable receiver adapter/connection mapping proofs, current source authorization over trusted HTTP, receiver admission checks and inherited receiver-owned children; default startup configures no remote access. See [remote bindings](docs/REMOTE_BINDINGS.md).
A native COMPLETED response alone does not validate an application's results or
prove that an uncertain external effect stopped.

## Checks

```powershell
npm run check
npm audit
npm run check:python
# Disposable test DB only: enables actual native queue/API/PostgreSQL cases.
$env:FACTORY_TEST_DATABASE_URL = 'postgresql+psycopg://test-user@127.0.0.1:5432/disposable_test_db'
uv run python scripts/check_python.py
```

`npm run check` includes shared frontend lint, type checks, tests and the composed build. `npm run check:python` runs Ruff and Pyright across core, deployment and scripts, then `scripts/check_python.py` discovers `platform/tests` with explicit synthetic fixtures. Any test failure makes the command fail. Without a test database, PostgreSQL cases explicitly skip. The opt-in loopback test identity needs CREATEDB on a disposable server: each test class creates and removes only its own randomly named database; supplied database tables are never cleared. CI runs frontend and Python checks on Windows/Linux and a separate pinned PostgreSQL integration job. All tests use synthetic input and make no paid provider calls.

[TOKEN_LEDGER.md](docs/TOKEN_LEDGER.md) describes provider-attempt accounting and
transactional reservations. BYOK and host-paid execution retain their distinct
accounting contracts. See [architecture](ARCHITECTURE.md),
[development checks](docs/DEVELOPMENT_CHECKS.md), [security](docs/SECURITY.md),
[delegation](docs/DELEGATION.md), [scheduling](docs/SCHEDULING.md) and
[remote resources](docs/REMOTE_RESOURCES.md) for shared mechanisms.

## Current acceptance and remaining work

Core-only acceptance requires login, logout/relogin, direct URLs and refresh,
empty catalog/task states, resource management, explicitly published synthetic
applications, native queue behavior and independent core installation. Test-only synthetic identity validates the real protocol without establishing
compatibility with an external production identity provider.
Use fresh isolated databases/workspaces and run heavy PostgreSQL/browser checks
serially. Results for this change belong in its Draft PR, not in historical counts.

## Historical Research acceptance

The records below describe earlier revisions with the now-removed application.
They preserve measured successes, failures and UNKNOWN outcomes; their commands,
paths and backlog are not current installation instructions. The
[development checkpoint](docs/DEVELOPMENT_IMPLEMENTATION_CHECKPOINT.md),
[requirements audit](docs/V03_FINAL_REQUIREMENT_AUDIT.md),
[ORX experiments](docs/ORX_LOCAL_EXPERIMENTS.md) and
[environment continuation](docs/ENVIRONMENT_CONTINUATION.md) are also historical
Research references pending documentation cleanup.

On 2026-10-07 the local owner verified the [first real autoresearch baseline](docs/RESEARCH_BASELINE_ACCEPTANCE.md):
302.587995 counted training seconds, independent fixed evaluation
`val_bpb=1.6711944975804394`, checkpoint and released custody. This uses the PR54
runner and sealed PR50 runtime; it does not certify production, department capacity,
multi-host operation or autonomous candidate improvement. See the
[current matrix](docs/ACCEPTANCE.md#current-matrix) and
[remaining original-plan priorities](docs/RESEARCH_BASELINE_ACCEPTANCE.md#what-this-closes-and-what-remains).

### Historical PR15/diagnostics-stage status

The following stage record predates later Go/PubMed and baseline acceptance.
Its then-current gaps and UNKNOWN results are preserved, not today's backlog.

The preceding exact-head baseline is `45eeb6b88046a40f8743e01e69d10353be386499`
([Draft PR15](https://github.com/Guanzhw/agent-factory/pull/15)): push/PR CI passed
all ten jobs, observed twice 106.515 seconds apart; each PG suite ran 650 tests
with 63 explicit skips. Its first real DeepSeek smoke attempt stopped UNKNOWN;
GPT-6-Luna was not called. That offline-only continuation added durable safe
diagnostics and corrects the unexplained version selection for `deepseek-flash`;
it does not change the old outcome or send another request. See
[current matrix](docs/ACCEPTANCE.md#current-matrix),
[diagnostic boundaries](docs/GO_SAFE_DIAGNOSTICS.md) and
[delivery index](docs/DELIVERY_INDEX.md). Its exact-head CI was recorded in that Draft PR.

| Available and measured | Boundary still open |
|---|---|
| Six-kind material governance, immutable plans/bindings, native queue, HITL, durable control receipts, cancellation, delegation, usage ledger and Chinese UI | Production/scientific acceptance is separate from controlled-provider execution |
| Actual pinned Linux ORX toy, local and receiver AT10 recovery including receiver-parent, same native/ORX identities and one launch | Fixed toy/evaluator; Windows and target-host reliability remain separate acceptance |
| Historical, now removed Go development profile: exact Chat/Responses model selection through native queue, loopback HTTP SSE, tool, receipt/artifact and PostgreSQL usage | Coding checksum scope only. Bounded live campaign stopped on first UNKNOWN smoke attempt; no live product success. Not a research provider |
| Literature source/package tools and controlled native evidence downloads | Actual PubMed attempt returned **0 sources** after connectivity failure; no successful live retrieval or scientific synthesis evidence |
| Governed Factory receiver execution, runtime attachment and resource lifecycle contracts | No real compute allocator/environment provisioning implementation; production remote TLS/identity/host setup is absent |
| Storage quarantine, finite twenty-user pressure and online PostgreSQL snapshot/restore | Measured **4 CPU / 16 GiB**; target **32 cores / 64 GB** or **54 cores / 192 GB** is unmeasured. Single active scheduler only |

At that historical stage, the default AutoResearch application selected **synthetic** materials and a
deterministic model. Its successful demo output is not a real research result.
Independent code remains for production browser identity/session integration;
a specific production research provider's adapter, usage/retry/request/pricing
contract and governed model selection; and a non-toy research workflow with
reviewed query/source/dataset/evaluator/workspace and change-approval contracts.
Credentials alone do not complete these implementations. Real compute allocation
also needs a provider implementation if that scope is selected.

No production IdP, provider or research use case has been selected by this stage.
See [minimum decisions](docs/PRODUCTION_DECISIONS.md) and
[Go live gates](docs/GO_DEVELOPMENT_PROFILE.md). Existing usage authorization is
not being re-requested; the authorized bounded campaign is now stopped after an
unknown outcome. A new live attempt requires a follow-up decision.

The normal department policy is now `member-self-service`: new tasks do not require ordinary plan approval, and historical review pages are read-only. Earlier administrator-review behavior remains documented in [historical plan policy and tested boundaries](docs/PLAN_POLICY.md); the current behavior and migration rules are in [department collaboration](docs/department-minimal-integration.md). Native hazardous-operation consent and live identity/model/ORX acceptance remain separate.

Trusted execution location selection and receiver-owned task trees are described in
[REMOTE_HANDOFF](docs/REMOTE_HANDOFF.md). No remote target is enabled by default.
Guarded hard-process schedule recovery and its native lease-release limitation are
recorded in [SCHEDULING](docs/SCHEDULING.md). Exact-source ORX build/preflight is
recorded separately from unverified live research.

Material-driven composition and compatibility rules are described in [MATERIAL_ASSEMBLY.md](docs/MATERIAL_ASSEMBLY.md). Members configure persistent [CLI/MCP tools](docs/MEMBER_TOOLS.md) and owned/shared resource connections through the normal APIs. Installations may also supply trusted same-process `Settings.runtime_adapters` and `Settings.trusted_connections`. Publication and execution use the selected adapter identities and current descriptors. Historical reviews retain their original contents; plans without explicit execution bindings must be regenerated. Original request IDs still recover their original operations.

Versioned publication/import and current material guards are described in
[material governance](docs/MATERIAL_GOVERNANCE.md). History pagination is documented
in [event replay](docs/EVENT_REPLAY.md). Actual twenty-user admission and clean-stop
PostgreSQL backup/restore evidence are in [operations](docs/OPERATIONS.md).

[Background lifecycle cleanup](docs/LIFECYCLE.md) observes current authority and descendant stop evidence without requiring the research page to poll.
