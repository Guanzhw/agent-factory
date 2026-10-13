# Architecture

Agent Factory serves a small departmental team on Agno AgentOS 3.1.0 and PostgreSQL. Its reusable core manages scoped execution; applications deliver research and other user workflows. Prefer removing unnecessary steps and duplicated responsibilities before introducing new abstractions.

| Responsibility | Owns | Dependency direction |
| --- | --- | --- |
| Core | Native runtime integration, current owner/task authority, immutable bindings, budgets, admission, cancellation and effect reconciliation | Generic contracts and shared implementation; never a concrete application, directly or indirectly |
| Application | User workflow, domain inputs/results, app-specific tools, presets and policy | Core and selected adapters; another app only through an explicitly declared public API |
| Adapter | A concrete provider, protocol or execution environment behind a trusted contract | Core contracts; application-specific integration belongs with that application |
| Composition root | Selecting installed applications and wiring trusted registrations at startup | Explicit app entrypoints and core; reusable core/apps must not import it |

Keep genuinely shared helpers shared. A directory move does not establish these responsibilities. Composition exceptions name individual files, never whole directories. They permit wiring, not a second place for application behavior or a route around core isolation.

Three acceptance boundaries:

1. **Independent core:** build and install the core without app source, then start its real lifecycle against disposable PostgreSQL, check health, and shut down cleanly. Import-only tests do not prove this.
2. **Dependency direction:** check direct and indirect imports, including package initializers and adapters. Cross-app callers may use declared public APIs; private implementations remain owned by their app. The checker must demonstrate legal, direct-violation and indirect-violation fixtures and report an actionable import chain.
3. **Ordinary workflow:** deterministic provider fixtures prove the selected model remains selected, owners remain isolated, revoked authority prevents new effects, normal personal submission adds no administrator review, and UNKNOWN acknowledgements do not replay work. Synthetic fixtures do not establish live provider compatibility.

Current migration status: implementation remains largely flat in `platform/agent_factory`, and `main.py` still assembles research-specific components. The configurable checker has synthetic coverage, but **no repository ownership map or app-free startup gate is enabled yet**. The application split must supply real package ownership, public entrypoints, exact composition files and an installable core startup command before these gates can claim success. Existing coupling is not exempted.

The product permission target is deliberately small: only deletion of shared/public resources needs administrator resource-management authority. Current identity, credential isolation and task bounds remain enforced. Historical plan/publication review machinery is being simplified separately; architecture work must not add or silently change production authorization. Runtime ownership, known limitations and prior evidence are in [RUNTIME_DESIGN.md](docs/RUNTIME_DESIGN.md); commands are in [DEVELOPMENT_CHECKS.md](docs/DEVELOPMENT_CHECKS.md).
