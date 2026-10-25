# Architecture

Agent Factory aims to provide reusable identity, tool and workflow execution foundations for a trusted departmental team on Agno AgentOS 3.1.0 and PostgreSQL. Members should be able to use their preferred Agent/client to compose CLI tools, MCP tools and skill materials with explicitly selected personal or shared resource connections. The core owns scoped execution, credential custody and binding continuity; applications package research and other workflows on top. Current identity-binding evidence and remaining acceptance are recorded in the [foundation plan](docs/plans/reusable-tool-identity-bindings.md). Prefer removing unnecessary steps and duplicated responsibilities before introducing new abstractions.

| Responsibility | Owns | Dependency direction |
| --- | --- | --- |
| Core | Native runtime integration, current owner/task authority, immutable bindings, budgets, admission, cancellation and effect reconciliation | Generic contracts and shared implementation; never a concrete application, directly or indirectly |
| Application | User workflow, domain inputs/results, app-specific tools, presets and policy | Core and selected adapters; another app only through an explicitly declared public API |
| Adapter | A concrete provider, protocol or execution environment behind a trusted contract | Core contracts; application-specific integration belongs with that application |
| Composition root | Selecting installed applications and wiring trusted registrations at startup | Explicit app entrypoints and core; reusable core/apps must not import it |

The agreed directory contract is encoded in the [Python ownership map](scripts/architecture-python.json) and [frontend ownership map](scripts/architecture-web.json); these are the authoritative paths and exact composition exceptions. The default deployment and browser composition register no applications. The former Research source, pages and seeds are removed; core `create_app` and the standalone wheel remain independent of application code. Members explicitly publish application/material definitions, while new trusted adapters require deployment registration. No cross-application API is currently declared.

Keep genuinely shared helpers shared. A directory move does not establish these responsibilities. Composition exceptions name individual files, never whole directories. They permit wiring, not a second place for application behavior or a route around core isolation.

Three acceptance boundaries:

1. **Independent core:** build and install the core without app source, then start its real lifecycle against disposable PostgreSQL, check health, and shut down cleanly. Import-only tests do not prove this.
2. **Dependency direction:** check direct and indirect imports, including package initializers and adapters. Cross-app callers may use declared public APIs; private implementations remain owned by their app. The checker must demonstrate legal, direct-violation and indirect-violation fixtures and report an actionable import chain.
3. **Ordinary workflow:** deterministic provider fixtures prove the selected model remains selected, owners remain isolated, revoked authority prevents new effects, normal personal submission adds no administrator review, and UNKNOWN acknowledgements do not replay work. Synthetic fixtures do not establish live provider compatibility.

CI runs both ownership maps, the independent core installation/lifecycle smoke and deterministic application regressions. There is no migration allowlist. Current integration findings and checker limitations are recorded in [development checks](docs/DEVELOPMENT_CHECKS.md); a failing boundary must be repaired before this integration can be accepted.

The product serves a trusted small team. Active members create and use components/workflows and publish their own applications/materials. Resource owners manage personal/team sharing, changes and withdrawal; account administrators manage accounts. Current membership, owner isolation, credential custody and task bounds remain enforced. Historical plan/publication reviews remain owner-readable records while new work uses member self-service. Runtime ownership, known limitations and prior evidence are in [RUNTIME_DESIGN.md](docs/RUNTIME_DESIGN.md); commands are in [DEVELOPMENT_CHECKS.md](docs/DEVELOPMENT_CHECKS.md).

A new empty database exposes the shared login, empty application catalog, task and
resource workspace. Test-only native fixtures explicitly install synthetic
applications; they are not startup defaults. Product demo login and bundled mock
identity providers are removed. An unconfigured public identity boundary rejects
authentication; test-only OIDC peers do not prove organization identity-provider
compatibility. Core-only acceptance is recorded in
[the exact-revision verification](openspec/changes/remove-research-verify-core/verification.md);
historical Research evidence remains historical.

Application retirement does not remove old database records, credentials, vault
keys, artifacts or backups. Old application tasks require their original code to
resume. Validation uses new isolated databases/workspaces; permanent old-data
deletion still requires an exact inventory and separate confirmation.
