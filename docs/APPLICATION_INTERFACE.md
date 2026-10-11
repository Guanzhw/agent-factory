# Public application interface v1

This interface gives reviewed applications a small Factory boundary. It does
not replace Agno, AgentOS, OpenResearch, or an executor's native continuation.
It is independent of the existing application definition contracts v1 and v2;
definitions and historical immutable plans keep their original hashes.

## Authority and ownership

| Layer | Owns | Does not decide |
| --- | --- | --- |
| Factory | User identity, credential vault, resource and application version pins, task admission, original intent/receipt, result index and scoped cleanup | Model/tool loop, business success, executor checkpoints |
| Executor | Native session, loop, execution state, original operation lookup, checkpoint and actual stop evidence | Factory permissions, application publication, changed owner or expanded scope |
| Application | Business input, workflow, success criteria, domain output and UI | Credential custody, global retry/recovery, proof of stop from an HTTP acknowledgement |

The native queue and external operation ledger remain the durability owners.
`ControlCommands` persists one original user decision and dispatches through
the original native/remote/delegation binding. `FactoryLifecycleObserver`
requests cleanup of existing owned work and observes executor/effect stop
evidence. Repeated cleanup signals are not new application submissions.
Unknown acknowledgement stays unknown: read the original request or operation.
Never resend an original goal to infer whether it previously ran.

Ordinary eligible owner tasks use the existing `OwnerSubmissions` checks in
Factory admission. A published application is not permission to auto-approve
shared code, arbitrary environments, remote placement or increased budgets.
Managed/shared work retains its configured policy. The immutable plan is an
internal admission record; ordinary applications need not implement a plan UI.

## Application code

The public Python types are in `agent_factory.application_interface`.
An operator-built native Agno function may declare the keyword
`application_context: ApplicationExecutionContext`. Factory injects it after
validating the original native ticket and consuming the existing step budget.
Functions using the historical `run_context` signature continue to work.

The context exposes only:

- Frozen owner/task/run/application identity.
- Independent input and resource-reference snapshots. No secret, endpoint,
  configuration body or executable connection handle is projected.
- `emit_event(name, message, data)` with bounded data and an `application_`
  event prefix; this cannot impersonate Factory control events.
- `write_artifact(name, content, media_type)` using the existing output budget,
  safe filename, hash and task provenance. The default verification status
  remains `unverified`; saving a domain result does not verify its conclusion.

Each write checks the original native identity, current workflow pin and current
tool authority again. This isolates reviewed application dependencies; it is
not a sandbox against malicious Python introspection. Operator adapter wiring
may still use internal `BindingContext`; that context and `Store` are not public
application APIs.

[`examples/minimal_application.py`](../examples/minimal_application.py) is a
synthetic summary function using only this context. Register it as a reviewed
Agno Step with zero retries, an implementation fingerprint, exact governed
tools/materials and normal input/admission checks. The executable PostgreSQL
regression runs it in the original native Workflow and checks its scoped
artifact and event. This is an interface fixture, not a second business app or
evidence of real research/model compatibility.

## Lifecycle client

`ApplicationLifecycle` defines input/resource discovery, start, original-request
lookup, query, cancel, event replay and artifact access. `ApplicationClient`
implements that port over the existing authenticated Factory HTTP APIs. The
caller supplies an `httpx.AsyncClient` with its authorized authentication/CSRF
configuration and write retries disabled. The client retains no credentials
and checks `X-Factory-Expected-Owner` on every request.

```python
from uuid import uuid4
from agent_factory.application_client import ApplicationClient

application = ApplicationClient(authorized_http, owner_id=current_owner)
definitions = await application.inputs(selected_application)
resources = await application.resources()
intent = {
    'interfaceVersion': 1,
    'requestId': str(uuid4()),
    'application': selected_application,
    'mode': selected_mode,
    'goal': reviewed_goal,
    'inputValues': reviewed_inputs,
    'connectionRefs': reviewed_connections,
}
# Persist intent in the application's existing storage before sending once.
receipt = await application.start(intent)
detail = await application.query(receipt['job']['id'])
```

The new endpoints are `POST /api/factory/application-interface/v1/starts` and
`GET /api/factory/application-interface/v1/starts/{requestId}`. Start uses the
existing immutable-plan and task request ledgers, with request namespace
`application-start:`. It does not introduce a second queue or controller.
Existing `/plans`, `/instances` and definition v1/v2 APIs continue to work.

After a lost start response, use `application.request(original_request_id)`.
`prepared` means input was committed, not that a native task was admitted;
`unknown` means acknowledgement was not proven. A missing receipt cannot prove
absence of a concurrent original request. Neither response permits automatic
replay. The caller must retain the original request and its uncertain outcome.

Cancel requires a caller-persisted original `command_id` and returns the native
control receipt unchanged. It does not translate an accepted cancellation into
verified stop. Use the original command receipt and task query to observe
progress. Event replay retains the opaque owner/task-scoped cursor. Artifact
downloads require their `X-Content-SHA256` to match the returned bytes.

Pause/continue are optional executor-specific extensions. Interface v1 does
not advertise them as universally available or promise compatible checkpoint
semantics. In particular, same-session credential rebind and an environment
restart are distinct from resubmitting research.

## Compatibility and deprecation

Only the types/methods and routes documented here form application interface
v1. The repository package version does not make every Python module a stable
SDK. Existing application definition v1/v2 and their pins remain separately
versioned. Unsupported interface versions are rejected, never silently mapped.

Additive optional fields may be introduced within v1; clients must tolerate
unknown response fields. Removing required fields/methods or changing write,
identity, authorization or acknowledgement semantics requires a new interface
version. Deprecation must include a public migration example and an explicit
removal release, with at least two minor releases and 90 days of overlap.
Historical request/receipt and immutable definition formats remain readable
under the configured data-retention policy. Internal `Store`, `BindingContext`
and operator-only services carry no such compatibility promise.

Run `test_application_interface.py`, `test_application_interface_postgres.py`,
existing native Workflow and definition v1/v2 regressions, and
`scripts/check_boundaries_postgres.py`. The latter requires all 25 named cases
to run against a disposable PostgreSQL database without skips.
