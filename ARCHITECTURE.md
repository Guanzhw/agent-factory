# Architecture

Agent Factory serves a small departmental team on Agno AgentOS 3.1.0 and PostgreSQL. Its reusable core manages scoped execution; applications deliver research and other user workflows. Prefer removing unnecessary steps and duplicated responsibilities before introducing new abstractions.

| Responsibility | Owns | Dependency direction |
| --- | --- | --- |
| Core | Native runtime integration, current owner/task authority, immutable bindings, budgets, admission, cancellation and effect reconciliation | Generic contracts and shared implementation; never a concrete application, directly or indirectly |
| Application | User workflow, domain inputs/results, app-specific tools, presets and policy | Core and selected adapters; another app only through an explicitly declared public API |
| Adapter | A concrete provider, protocol or execution environment behind a trusted contract | Core contracts; application-specific integration belongs with that application |
| Composition root | Selecting installed applications and wiring trusted registrations at startup | Explicit app entrypoints and core; reusable core/apps must not import it |

The agreed directory contract is encoded in the [Python ownership map](scripts/architecture-python.json) and [frontend ownership map](scripts/architecture-web.json); these are the authoritative paths and exact composition exceptions. Deployment probes/campaigns belong in `deployment/verification`. Research configuration, installation and services belong to `agent_factory_research.config.ResearchSettings`, `.assembly.install_research` and `.services.ResearchServices`; core `create_app` must work without installing them. No cross-application API is currently declared; composition may wire the research app directly.

Keep genuinely shared helpers shared. A directory move does not establish these responsibilities. Composition exceptions name individual files, never whole directories. They permit wiring, not a second place for application behavior or a route around core isolation.

Three acceptance boundaries:

1. **Independent core:** build and install the core without app source, then start its real lifecycle against disposable PostgreSQL, check health, and shut down cleanly. Import-only tests do not prove this.
2. **Dependency direction:** check direct and indirect imports, including package initializers and adapters. Cross-app callers may use declared public APIs; private implementations remain owned by their app. The checker must demonstrate legal, direct-violation and indirect-violation fixtures and report an actionable import chain.
3. **Ordinary workflow:** deterministic provider fixtures prove the selected model remains selected, owners remain isolated, revoked authority prevents new effects, normal personal submission adds no administrator review, and UNKNOWN acknowledgements do not replay work. Synthetic fixtures do not establish live provider compatibility.

CI runs both ownership maps, the independent core installation/lifecycle smoke and deterministic application regressions. There is no migration allowlist. Current integration findings and checker limitations are recorded in [development checks](docs/DEVELOPMENT_CHECKS.md); a failing boundary must be repaired before this integration can be accepted.

The product serves a trusted small team. Active members create and use components/workflows and publish their own applications/materials. Resource owners manage personal/team sharing, changes and withdrawal; account administrators manage accounts. Current membership, owner isolation, credential custody and task bounds remain enforced. Historical plan/publication reviews remain owner-readable records while new work uses member self-service. Runtime ownership, known limitations and prior evidence are in [RUNTIME_DESIGN.md](docs/RUNTIME_DESIGN.md); commands are in [DEVELOPMENT_CHECKS.md](docs/DEVELOPMENT_CHECKS.md).
