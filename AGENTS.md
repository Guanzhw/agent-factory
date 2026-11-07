# Project instructions

## Choose the relevant context

- Before changing package ownership or composition, read [ARCHITECTURE.md](ARCHITECTURE.md) and the ownership maps linked there.
- Before changing execution, cancellation, recovery, or resource bindings, read [Runtime design](docs/RUNTIME_DESIGN.md) and its relevant component reference.
- Before validating a change, read [Development checks](docs/DEVELOPMENT_CHECKS.md). Report executed checks separately from commands that were not run.
- Before changing research behavior or navigation, read the [autonomous Agent decision](docs/plans/agent-autonomy-20261106.md). The product has one research entry. The Agent chooses its tools and next actions.
- For older designs and evidence, use the [documentation map](docs/DOCUMENTATION_MAP.md). A historical acceptance report applies to its recorded revision and environment.

## Preserve the product boundaries

Use Agno AgentOS 3.1.0 and PostgreSQL. Reuse the installed SDK's Registry, native model and tool loop, queue, and lifecycle before adding a replacement. Record a concrete SDK gap when a replacement is necessary.

Core owns execution and resource interfaces. Research concepts belong in `applications/research`. The composition root selects applications and trusted adapters. One product UI does not remove the standalone core package or its programmatic API.

The platform serves a trusted small team. Members create and use components, publish their own content, and connect resources. Account administrators manage accounts. Resource owners choose personal or team sharing. Shared use never exposes their credentials. Input validation belongs at the boundary that owns the operation.

Keep correct user/resource association, original-operation receipts, and evidence that owned processes stopped. Missing acknowledgements remain uncertain until the original operation is reconciled. A request timeout or canceled queue ticket is not proof that compute stopped. These operational rules do not require a new approval system or a fixed research workflow.

## Implement and review

1. Inspect callers and the pinned SDK before changing a shared contract.
2. Reproduce the user-visible failure or run one small authorized real task.
3. Prefer installed Agno capabilities over duplicate implementations. Remove project restrictions that obstruct Agent execution or add user steps. For autonomous-session limits, compare the same scope and units against the pinned Codex reference; do not replace a lifetime quota with an unrelated concurrency value. New abstractions or compatibility paths need a present requirement or reproduced failure.
4. Run relevant checks and review the complete diff. Independent review checks correctness, removable code, and reusable native capabilities.
5. Open a Draft PR using the repository template. Report behavior, evidence, remaining limitations, and next steps. Merge only with applicable user authorization.

For delegated work, state the user outcome, writable files, acceptance check, and non-goals. A discovered dependency requires an explicit scope update.

Check limits against the real task. Earlier 12 KB file limits, eight-call tool budgets, short model deadlines, and small output-token settings blocked otherwise valid work. Raising a constant alone does not establish usability. Keep failed runs as evidence and separate product requirements from arbitrary QA restrictions.

## Protect existing work

Commit public code, public documentation, and synthetic fixtures only. Keep credentials, private design packages, personal files, databases, logs, and generated research outside the repository. Preserve third-party notices and existing user changes.

Use the authorization already supplied in the task for models, compute, and deployment. Confirm any new access or security-sensitive change that falls outside it. Source retirement does not authorize deleting stored user data, credentials, or backups.
