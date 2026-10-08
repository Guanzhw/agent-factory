# Governed workflow agents

This extension is a generic workflow mechanism, not a ConvertD implementation.
No actual ConvertD source, data, backend or environment was supplied. The named
six-phase business description is design input, not verified business behavior.
The integration fixture uses synthetic stages and outcomes; it proves only the
engineering boundaries listed below.

## Registration and application assembly

An operator installs trusted `AdapterRegistration` objects and exact
`ToolPolicyRegistration(name, capability, revision, read_only, adapter_id,
adapter_revision)` descriptors in `Settings`. Existing built-in tool identities
cannot be overridden. The governance and plan-policy fingerprints include these
registrations; withdrawal or revision drift rejects new execution. A custom tool
must pin the corresponding adapter and capability in its published material.
Application users can select approved materials, but cannot upload executable
factories, install adapters, enlarge capabilities or publish their own approvals.

A mode may declare a bounded `inputSchema`. Composition accepts `inputValues`
separately from the existing executor `TaskConfig`, validates them and binds both
to immutable proposal/plan hashes. The schema subset includes objects with
`additionalProperties:false`, bounded arrays/strings, numbers, integers, booleans,
null and scalar enums. References, code and network schema loading are rejected.
The UI supports simple forms and bounded JSON for nested values. These are
ordinary application inputs, never a credential provisioning interface. A
trusted domain adapter must independently authorize referenced files/resources.

An operator installs workflow definitions and runtimes using
`Settings.workflow_definitions` and `Settings.workflow_runtimes`. The five
registrations from `workflow_profile.registrations(definitions)` pin
`workflowId` and `workflowSha256` in tool bindings. Definitions contain a bounded
acyclic graph (at most 16 stages), exact runtime adapter revisions, dependencies,
human gates, failure-code routes and a parallel-operation limit. They contain no
URLs, shell commands or executable modules. Definition withdrawal remains a
current-policy denial; persisted custody is retained even if all registrations
are removed at restart.

## Native execution and durable recovery

The application's registered Agno model chooses stages through actual native
calls to `workflow_read`, `workflow_choose`, `workflow_inspect`, `workflow_wait`
and `workflow_finish`. The platform does not substitute a fixed business script
for the model. The fixture model is explicitly synthetic and deterministic.

`workflow_read` initializes the original workflow once and reads its state; it
is not a read-only policy tool. Stage selection writes an original operation ID
and UNKNOWN intent before calling its trusted runtime. Runtime callbacks execute
outside workflow SQL locks. Separate choose calls can leave several operations
running up to `maxParallel`; a dependent join cannot start until its exact
prerequisites have completed or their matching failure recovery has completed.
A failed source retains FAILED and its structured failure code. Untriggered
failure branches are marked SKIPPED only when the model explicitly finishes.

`workflow_wait` uses Agno's external-execution pause. The native worker is freed;
no replacement run is created. When an explicit reconcile or human decision
makes that original requirement ready, the existing durable ControlCommands
protocol continues the same task/run/tool-call identity. The completion signal
is stable across unrelated stage updates; the model then reads current state.
External continuation debits the shared tool ledger using the original native
tool-call ID, because Agno external execution does not run the normal tool hook.
Repeated preparation reuses that identity; receipt reads do not debit it.
Human approval is an owner-scoped versioned API command, not an agent tool.

A runtime implements `start(context, operation_id, inputs)`,
`inspect(context, original_handle)`, `cancel(context, original_handle)` and,
for lost-start-ACK recovery, read-only `lookup(context, operation_id)`. Returned
observations pin the original operation/adapter/revision/handle and bound all
output/failure data. Terminal results require positive `allStopped` evidence.
An absent handle, failed lookup or timeout never means stopped. UNKNOWN is held;
start is never retried automatically. Cancellation may recover an original
handle through lookup and then stop it, including after authority has ended.
Missing original adapters leave custody held rather than releasing capacity.
An adapter can explicitly raise `WorkflowAcknowledgementUnknown` when a start
may have reached its backend but no acknowledgement is available. The service
rechecks current authority and returns its durable UNKNOWN intent for a native
pause and later original-ID lookup. Ordinary exceptions still trigger protected
failure cleanup; cancellation is never converted into a successful observation.

This protocol does not implement an arbitrary runtime engine, sandbox, compute
allocator or notifications backend. Installed adapters remain trusted code and
must apply domain authorization, before-effect rechecks and existing resource,
wall-time, usage and process custody services appropriate to their effects.
Native tool calls and explicit stage resumes debit the existing shared tool
budget. Parallel stage count alone is not a CPU/memory/monetary budget.

## API and frontend

- `GET /api/factory/workflows/{taskId}` returns an owner-scoped snapshot and
  current allowed actions, or `{available:false}` for a non-workflow task.
- `POST /api/factory/workflows/{taskId}/commands` accepts a stable `commandId`
  and exactly one action: `decide`, `resume`, `reconcile` or `cancel`. All stage
  actions require `stageId` and the observed `version`; decide also requires
  `approved`. Cancel carries no stage/version/decision.
- `GET /api/factory/workflows/{taskId}/commands/{commandId}` reads and reconciles
  that original receipt from positive journal/native evidence. It never starts
  an operation or dispatches a native continuation.

Known pre-dispatch refusal is recorded as `rejected`. Once dispatch may have
happened, errors remain `unknown` or `recorded` until original evidence resolves
them. Exact duplicate submissions do not repeat effects; changed content under
the same command ID conflicts. `completed` describes handling of the command,
not proof that the whole workflow or all external processes stopped.

The frontend retains unresolved command identity across refresh, reads its exact
receipt, and allows scoped reconciliation/cancellation while blocking new
stage decisions. Only a receipt lookup returning 404 permits an explicit retry
of the exact original payload. Reconcile inspects an original operation and may
continue the original ready native wait; it does not restart that operation.
Resume means selecting an admissible, unstarted stage with retained prerequisite
results, not resetting or replaying a failed/unknown stage.

## Engineering evidence and limits

`test_workflow_native_postgres.py` and the mandatory
`scripts/check_workflow_postgres.py` gate run four synthetic cases with zero
allowed skips. They execute real PostgreSQL records, native Agno queued tool
invocation, loopback HTTP and an actual server-process restart using the same
persisted database. A durable SQLite fixture represents external operations;
no real provider/backend/notification is called. Cases cover original task/run
and operation identities after restart, a freed single native worker, parallel
stages and join, versioned human decision, structured failure-to-B routing,
lost ACK lookup without duplicate starts, owner isolation, revocation and
cancellation. They do not produce or validate real ConvertD outputs, scientific
results, production identity, cross-host execution or target capacity.
The separate pre-pause exit case terminates the server after UNKNOWN is durable
but before the native pause is committed. Conservative cancellation is allowed;
original starts must remain unique, and capacity release requires positive stop
evidence. This differs from the already-paused lost-acknowledgement recovery case.

Unit checks separately cover strict schemas and immutable input hashes,
registered policies, failure graph rules, terminal monotonicity, missing-adapter
custody, stable native requirements and read-only command recovery. Existing
AutoResearch and candidate PostgreSQL gates remain mandatory. Final exact commit,
CI outcomes and independent review are recorded in the PR/task board; a passing
synthetic gate is never a claim of live business acceptance.

`scripts/accept_workflow_browser.py` exercises the real React components in a
browser with an injected synthetic API, including versioned decisions, preserved
UNKNOWN intent after reload, GET receipt recovery, explicit same-payload retry
after 404, pending cancellation and a 390-pixel viewport. It does not replace the
separate native/PostgreSQL checks or certify a live backend.
