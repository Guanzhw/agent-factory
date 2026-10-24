# Project instructions

Start with [ARCHITECTURE.md](ARCHITECTURE.md) for responsibilities and the three acceptance boundaries. [Development checks](docs/DEVELOPMENT_CHECKS.md) gives runnable commands and current limitations. Runtime mechanisms and their existing evidence remain in [RUNTIME_DESIGN.md](docs/RUNTIME_DESIGN.md); they are not extra product approval requirements.

The selected platform is Agno AgentOS + PostgreSQL, targeting Agno 3.1.0. Reuse native Registry, components and execution lifecycle. Keep task execution in the native runtime. Existing TypeScript/legacy SDK scaffolding is not the selected engine.

Product spine: reusable materials and applications, member-owned resource connections, and observable execution. The core owns general execution and resource interfaces; research concepts and workflows belong to the research application. Credentials belong to resource owners and are not exposed through shared catalog content.

The product serves a trusted small team. Administrators manage accounts only. Members may create and call components/workflows, publish applications/materials, schedule work and connect resources themselves. Resource connections have no address, host, port or per-resource operator allowlist. Owners manage their resources and choose personal or team sharing; shared use does not expose credentials. These decisions supersede older approval, administrator-only publication/withdrawal and fine-grained capability requirements. Validate inputs at their owning boundary and trust internal contracts. Keep cancellation, resource limits and original-operation recovery for their operational purpose, separate from authorization. Prefer removing obsolete policy paths over adding a permissive-mode switch.

Commit only new safe code, public docs and synthetic fixtures. Do not copy private design packages, credentials, personal files or company data into this public repository. Preserve third-party licenses and notices. Paid models/compute, deployment exposure and new access require explicit authorization. Open PRs as drafts; do not merge automatically.

Run `npm run check` and dependency audit for relevant changes. Verify actual runtime/browser behavior when it is available. Label model/ORX integration as unverified until it has run successfully; a client import or synthetic test does not prove live compatibility. Keep the acceptance matrix honest and distinguish planned from implemented features.

Remote runtime attachment and remote compute are foundational. Implement one selected-runtime adapter first; separate create/attach from environment allocation, reconcile unknown acknowledgements, retain scoped cancellation and artifact provenance. Single-server target profiles are 32 cores/64 GB and 54 cores/192 GB; no cluster or permanent heavy instance per user. Record actual host measurements separately from capacity targets.

Make incremental changes with concrete behavior checks. Share helpers when they express a real common responsibility; keep app-specific policy in its app or adapter. Report changed behavior, verification, unverified scope and next step using the short PR template. Development model preferences are task configuration, not permanent product capability bans. Do not add an approval system, long per-change specification, or evidence platform to enforce these instructions.
