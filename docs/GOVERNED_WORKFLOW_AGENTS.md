# Governed native workflow agents

Agno 3.1 owns workflow progress, step results, routing, human requirements and
continuation. Factory assembles approved materials around a native `Workflow`,
pins its identity, checks current authority, accounts for shared budgets and
retains custody of external effects. Factory does not maintain a second DAG,
stage scheduler or independent resume engine.

This is a generic integration mechanism. The user implements real ConvertD
locally. No ConvertD source, domain backend or production dataset is supplied by
this repository's synthetic fixtures. Neither the examples below nor a mock
browser interaction establishes live backend or business-result acceptance.

## Execution ownership

The implementation boundaries are:

| Module | Responsibility |
| --- | --- |
| [`native_workflows.py`](../platform/agent_factory/native_workflows.py) | Validate operator-built native components; bind their function and Agent steps to the original owner, plan, envelope and native queue ticket. |
| [`native_component.py`](../platform/agent_factory/native_component.py) | Immutable `kind/id/revision/sha256` component coordinates; no execution state. |
| [`workflow_model.py`](../platform/agent_factory/workflow_model.py) | Route a registered decision Agent through the plan's existing model binding, authority and usage accounting. |
| [`workflow_operations.py`](../platform/agent_factory/workflow_operations.py) | Original external-operation intent, handle, observation and positive stop evidence; no workflow progress. |
| [`workflow_control.py`](../platform/agent_factory/workflow_control.py) | Owner-scoped native projections and thin, idempotent command receipts for original native requirements. |

`Settings.native_workflows` accepts
`NativeWorkflowRegistration(component, revision, tool_names, implementation_sha256)`. `component` is an
operator-created Agno `Workflow`; `tool_names` lists its governed function-step
names. `NativeWorkflows.pin(id)` produces the exact pin placed in the published
application mode's `nativeComponent`. Composition carries it into the plan and
binding manifest. Native admission uses that registered workflow component,
not a substitute Factory executor that interprets a graph.

`implementation_sha256` is a required 64-hex commitment produced by the operator
from the reviewed implementation and configuration. The operator must define
and preserve the exact source/configuration manifest used to calculate it;
changing that implementation requires an updated reviewed registration. Agno's
`to_dict()` function names are not source-code hashes and do not substitute for
this commitment. In-process identity checks also bind the exact installed
wrapped executor, Router selector, Condition evaluator, Agent and model bridge.
Those checks detect replacement objects; they are not an independent disk-code
attestation or a sandbox for operator code.

The permitted native building blocks are `Step`, `Parallel`, `Router`,
`Condition` and `Steps`. Function steps require `max_retries=0` and explicit,
unique semantic ASCII `step_id` values and unique step names. Every step must
set `HumanReview(on_error=OnError.fail)` and keep `skip_on_failure=False`; the
default error-skip policy can otherwise leave failed steps under a completed
workflow. Structured domain failure outputs can still select reviewed recovery
branches through native `Condition` or `Router`. Auto-generated UUID declarations
are rejected. Agno creates and persists runtime step UUIDs when it copies a
workflow; these differ from declaration IDs. Continuation validates the original
owner-scoped WorkflowSession, root run, child Agent and persisted runtime step
identity. It must not compare a restored runtime UUID with a declaration ID. Use `max_retries=0` explicitly on all example steps; an unknown external
acknowledgement is not permission to retry a function. `Loop`, nested `Workflow`
steps and `Team` executors are not open in this integration.

Agent steps must have stable IDs and static instructions/system messages. A
decision Agent is tool-free. Executable Agent hooks, fallback models and extra
parser/model paths are rejected rather than treated as implied provider grants.
The exception is an Agent whose only tool is the
exact installed `factory_wait_operations` external-execution tool. An Agent with
that tool must be outside `Parallel`.

For asynchronous work, put bounded submission function steps inside native
`Parallel`, then place a wait Agent after the parallel block. Agno joining the
submission steps means those functions returned; it does not prove their
external jobs stopped. The wait Agent requests original operation IDs through
`factory_wait_operations`. Wait budget debits bind the original native step ID
and provider tool-call ID, so different Agent steps cannot share a debit accidentally.
Native external execution parks the original run;
Factory resolves that exact requirement only from matching operation custody.
The result is supplied with native `RunRequirement.set_external_execution_result`;
Agno consumes the external-execution flag and result itself. Clearing that flag
before continuation loses the result. No new run or replacement operation is
created to continue it.

For model-selected branching, use a named, tool-free Agent to produce a bounded
enum decision, then a native `Router` with an operator-authored selector. The
selector must validate the response, accept only the declared enum values and
return registered choices. It must not evaluate model-provided code, import a
module, construct arbitrary steps or infer a new workflow from free text. Native
`Condition` can select a reviewed recovery branch from structured outputs.
Factory's model bridge supplies the existing plan model and checks the registered
Agent/step against its original workflow root; it does not choose the branch.

## Input and tool-policy assembly

A published mode may contain the bounded declaration `inputSchema`; composition
accepts `inputValues` separately from executor `TaskConfig`. The declaration
supports closed objects, bounded arrays/strings, finite numbers, integers,
booleans, null and scalar enums. References, network schema loading, defaults and
executable extensions are outside the admitted declaration.

[`input_model(schema)`](../platform/agent_factory/input_schema.py) maps that
admitted declaration to an actual strict Pydantic `BaseModel` class. Pass the
class to `Workflow(input_schema=...)`. Pydantic validates values; the declaration
boundary adds resource limits and a narrow compatibility check for typed enums.
The application schema and native component schema must match. Composition pins
the original schema and values and their hashes; it does not replace omitted
values with defaults.

```python
from agent_factory.input_schema import input_model

INPUT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["documentRef"],
    "properties": {
        "documentRef": {"type": "string", "minLength": 1, "maxLength": 120}
    },
}
NativeInput = input_model(INPUT_SCHEMA)
checked = NativeInput.model_validate({"documentRef": "owned-public-fixture"})
values = checked.model_dump(by_alias=True, exclude_unset=True)
```

`by_alias=True, exclude_unset=True` preserves original JSON field names and
omission. Plain `model_dump()` can introduce optional `None` defaults and must
not be used to reconstruct immutable input values. The browser supplies forms,
bounded JSON and required-field hints; it is not a second schema authority.
A document reference does not itself grant file access. Domain adapters must
check the original owner's current access to the referenced resource.

Tool policy declarations have exactly four fields:

```python
from agent_factory.tool_policy_registry import ToolPolicyRegistration

policy = ToolPolicyRegistration(
    adapter_id="local-analyze-v1",
    adapter_revision="1",
    revision="1",
    read_only=False,
)
```

Name and capability come from one exact trusted `AdapterRegistration` with one
permission; they are not repeated in a user-editable policy declaration. The
resolved projection is approval evidence, not a second registration API. Built-in
tool identities cannot be overridden. Published tool materials pin the matching
adapter ID/revision and permission. The policy, current registrations and
material bindings are rechecked before execution.

Native function wrappers debit the shared tool ledger using the semantic
registered step ID. Decision Agents use the existing model dispatch and usage ledger under
the original workflow root. External-execution continuation separately debits
`factory_wait_operations` using the original native tool-call ID because that
pause/resolution path bypasses the ordinary tool pre-hook. Reading a snapshot or
command receipt is not a budget debit. A tool-budget receipt is not proof that an
external effect completed, and native parallelism is not a CPU, memory or price
limit.

## Complete synthetic wiring reference

Use the checked-in
[`test_native_workflow_factory_postgres.py`](../platform/tests/test_native_workflow_factory_postgres.py)
as the complete Factory assembly reference. It contains executable fixture
code, not a deployment command or real ConvertD implementation:

1. `INPUT_SCHEMA` / `WorkflowInput` construct the Pydantic native input class.
2. `build_workflow(holder)` builds actual Agno steps with semantic IDs and zero
   function retries, parallel submissions, a wait Agent after the join, native
   `HumanReview` and a final function step.
3. `settings(configuration, backend, holder)` registers model, environment,
   knowledge and tool adapters; four-field tool policies;
   `NativeWorkflowRegistration` including its reviewed implementation hash;
   original-operation runtime pins; and explicit
   fixture model pricing. The `holder` is populated after `create_app` so trusted
   executors can access the configured Store; it does not create a new queue.
4. `publish(state)` creates and separately reviews prompt, skill, knowledge,
   model, environment and tool materials. It publishes the application with
   exact material references, `nativeComponent`, `inputSchema`, capabilities,
   tool order and budgets.
5. The fixture's task-creation helpers follow composition proposal → acceptance
   → plan review/decision → instance admission. They do not bypass governance by
   inserting completed task rows.

The separate
[`test_native_workflow_reuse_postgres.py`](../platform/tests/test_native_workflow_reuse_postgres.py)
shows native Agent enum output → `Router`, structured failure recovery via
`Condition`, `Parallel` and original-run continuation. It is a native Agno
mechanism fixture, not evidence that every combination has passed the Factory
integration gate. Its standalone component examples must be adapted to the
Factory registration constraints above, including semantic step IDs.

Replace fixture identities, deterministic models, zero-price declarations and
SQLite operation backend with explicitly authorized local implementations.
Never deploy fixture control endpoints or copy a synthetic pricing assertion to
a live provider. Preserve the installed native execution owner rather than
reintroducing `workflow_read/choose/finish` tools, a custom graph definition or
an application-defined resume scheduler.

## External-operation custody

A trusted function step calls:

```python
record = await store.workflow.start(
    run_context,
    step_id="analyze",
    effect_slot="original",
    adapter_pin={
        "adapterId": "local-domain",
        "revision": "1",
        "configFingerprint": reviewed_backend_fingerprint,
    },
    inputs={"values": plan["inputValues"]},
)
```

`store.workflow` here is `OperationCustody`, not a workflow engine. Register its
backend under
`Settings.workflow_runtimes[(adapter_id, revision, config_fingerprint)]`. The
trusted runtime implements all four methods: `start(context, operation_id,
inputs)`, `lookup(context, operation_id)`, `inspect(context, original_handle)`
and `cancel(context, original_handle)`. Inputs are the explicitly supplied,
bounded object, not reconstructed DAG dependency outputs.

Factory durably reserves the effect slot and original operation ID before
calling `start`, then rechecks current authority outside the transaction. A
repeat of the same slot returns its original record; changed inputs or adapter
pins conflict. A typed `WorkflowAcknowledgementUnknown` retains UNKNOWN for
original-ID lookup. It must not be used to conceal arbitrary failures. Neither
missing handles nor failed lookup authorize replacement starts or stop claims.

The shared `WorkflowContext` type retains compatibility field names. For this
custody service, `workflow_id` carries the original Factory task ID,
`run_id` the native workflow run ID, `stage_id` the semantic native step ID and
`definition_sha256` the original plan hash. Adapters must bind these identities,
not infer a new workflow definition from the field names.

An observation binds the original operation, adapter revision and handle.
`COMPLETED`, `FAILED` or `CANCELLED` observations require positive `allStopped`
evidence; UNKNOWN remains held. Known handles cannot be replaced. Output and
failure data remain bounded, and structured failures carry symbolic codes, not
secrets or unbounded exception text. Domain adapters remain responsible for
real resource limits, before-effect checks and backend/process stop evidence.

Inspection and cleanup target original custody rather than minting a new
execution grant. Missing original adapters or uncertain stop retain the hold.
Native task termination alone cannot release unresolved external operations.
Factory admission, lifecycle, delegation and remote accounting must consult
this custody; the external-operation table never claims native step progress.

## Native API and browser behavior

`GET /api/factory/workflows/{taskId}` returns `{available:false}` or a schema-2
projection containing original component/owner/task/run/plan identities, native
status, step outputs, unresolved native requirements and separate external
operation stop evidence. `version` is a 64-hex snapshot digest, not a sortable
stage counter. `allowedActions` comes from the server.

`POST /api/factory/workflows/{taskId}/commands` accepts one stable `commandId`:

| Action | Additional fields |
| --- | --- |
| `decide` | Current `version`, exact `requirementId`, and either `approved` for native confirmation or `values` for native user input. |
| `reconcile` | Current `version` and original `operationId`. |
| `cancel` | None. |

There is no stage-selection or `resume` endpoint. Human decisions resolve the
original Agno `StepRequirement`. Reconciliation reads an original operation and,
when its exact external requirement is ready and authority remains current,
continues that same native run. The bridge uses native queue continuation; it
does not rebuild step results or enqueue a replacement workflow.

`GET /api/factory/workflows/{taskId}/commands/{commandId}` reads original command
evidence without starting operations or dispatching continuation. Receipts use
`recorded`, `unknown`, `completed` and `rejected`; handling a command is distinct
from completion or physical stop of the workflow. Changed contents under the
same command ID conflict. UNKNOWN must be reconciled from original evidence.

The browser stores bounded unresolved original command pointers, reads their
receipts, and permits explicit same-payload submission only after an exact 404.
It preserves concurrent pending cleanup pointers, blocks new human decisions
while commands are unresolved, and does not order snapshot digests. Historical
receipts cannot replace an already displayed GET snapshot. Native steps and
requirements are rendered as supplied; no client DAG infers dependencies,
branch completion or eligibility. External `allStopped` is displayed separately
from native status.

## Validation and delivery boundary

A completed native queue row is insufficient acceptance. The synthetic end-to-end
fixture also requires all six expected leaf step results to succeed and all five
expected external operations to start exactly once and positively stop. Preserve
these assertions across pause, process restart and original-run continuation.
Function continuation may omit `RunContext.workflow_id` in Agno 3.1; Factory
rebinds it only after validating the original ticket, owner, run, plan and envelope.
A conflicting workflow ID is rejected.

Technical examples and check entrypoints are source references, not claims that
the current commit has passed tests or CI. Use the repository's current CI and
`scripts/check_workflow_postgres.py` configuration for the selected native gates;
do not reuse counts from the removed graph-engine test suite. PostgreSQL tests
require a dedicated `FACTORY_TEST_DATABASE_URL`; skipped tests are not acceptance.

[`accept_workflow_browser.py`](../scripts/accept_workflow_browser.py) exercises
real React components with synthetic API transport on loopback. It covers input,
command recovery and narrow/mobile layouts. It does not exercise a live Factory
backend, PostgreSQL or real native execution. It accepts an optional existing
`--chromium-executable`; this is not a backend or deployment option.

Local ConvertD acceptance still needs the user's implementation, authorized
identity/provider configuration, resource environment and domain result checks.
Validate actual start/lookup/inspect/cancel, lost acknowledgements, restart,
revocation, positive stop, shared budgets and original-input/output identity.
Nothing in this document certifies real ConvertD outputs, target-host capacity,
production identity, cross-host execution or a live model connection.
