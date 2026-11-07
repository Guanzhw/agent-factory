# Project instructions

## Choose the relevant context

- Before changing package ownership or composition, read [ARCHITECTURE.md](ARCHITECTURE.md) and the ownership maps linked there.
- Before changing execution, cancellation, recovery, or resource bindings, read [Runtime design](docs/RUNTIME_DESIGN.md) and its relevant component reference.
- Before validating a change, read [Development checks](docs/DEVELOPMENT_CHECKS.md). Report executed checks separately from commands that were not run.
- Before changing research behavior or navigation, read the [autonomous Agent decision](docs/plans/agent-autonomy-20261106.md). The product has one research entry. The Agent chooses its tools and next actions.
- For older designs and evidence, use the [documentation map](docs/DOCUMENTATION_MAP.md). A historical acceptance report applies to its recorded revision and environment.

## Product and implementation

Use Agno AgentOS 3.1.0 and PostgreSQL. Reuse the installed SDK's Registry, native model and tool loop, queue, and lifecycle before adding a replacement. Record a concrete SDK gap when a replacement is necessary.

Core owns execution and resource interfaces. Research concepts belong in `applications/research`. The composition root selects applications and trusted adapters. One product UI does not remove the standalone core package or its programmatic API.

The platform serves a trusted small team. Members create and use components, publish their own content, and connect resources. Account administrators manage accounts. Resource owners choose personal or team sharing. Shared use never exposes their credentials. Input validation belongs at the boundary that owns the operation.

Start with a working chat experience and an Agent that completes real tasks. Put model and tool configuration in Settings and show understandable progress and results. Do not use safety design, execution boundaries, receipts, approvals or budgets as the starting point for product design. Remove extra layers that obstruct execution or add user steps. Preserve functional truth: report real failures, keep each user's data associated with that user, and make Stop actually stop owned work.

## Implement and review

1. Inspect callers and the pinned SDK before changing a shared contract.
2. Reproduce the user-visible failure or run one small authorized real task.
3. Prefer installed Agno capabilities over duplicate implementations. Remove project restrictions that obstruct Agent execution or add user steps. For existing autonomous-session limits, compare the same scope and units against the pinned Codex reference: remove limits without a corresponding Codex limit and align comparable defaults. Do not add a capability just because Codex has it. New abstractions or compatibility paths need a present requirement or reproduced failure.
4. Apply the installed [Ponytail skill](.agents/skills/ponytail/SKILL.md). The user requested deletion of the entire existing test suite. Do not restore it or add replacement tests without a later request. Validate real user outcomes directly; run relevant static checks and review the complete diff. Independent review checks correctness, removable code, and reusable native capabilities.
5. Open a Draft PR using the repository template. Report behavior, evidence, remaining limitations, and next steps. Merge only with applicable user authorization.

For delegated work, state the user outcome, writable files, acceptance check, and non-goals. A discovered dependency requires an explicit scope update.

Check limits against the real task. Earlier 12 KB file limits, eight-call tool budgets, short model deadlines, and small output-token settings blocked otherwise valid work. Raising a constant alone does not establish usability. Keep failed runs as evidence and separate product requirements from arbitrary QA restrictions.

## Protect existing work

Commit public code, public documentation, and synthetic fixtures only. Keep credentials, private design packages, personal files, databases, logs, and generated research outside the repository. Preserve third-party notices and existing user changes.

Use the authorization already supplied in the task for models, compute, and deployment. Confirm any new access or security-sensitive change that falls outside it. Source retirement does not authorize deleting stored user data, credentials, or backups.
