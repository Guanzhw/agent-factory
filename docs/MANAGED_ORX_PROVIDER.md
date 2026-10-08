# Managed native attachment: bounded turn contract

This implements a **single text-only turn probe**, not full research-agent tool
execution or live remote verification. It retains the original native project and
session. No model, server, credential, process supervisor or firewall is installed
by these modules.

## Existing owners reused

- Agno's original run pauses through `ManagedAttachmentControlModel`; existing
  Factory control commands validate and continue its native requirement.
- `PersistentResourceService` reserves the durable original lease and shared pool
  before dispatch. `ProcessRuntimeService` owns observation, cancellation and
  release. No new queue, retry scheduler or inference loop is introduced.
- `ORXResearchBroker` permits one provider request, with no native tools, and calls
  the real shared `UsageLedger` before credential access and provider dispatch.
  Missing usage remains held. Configured nominal prices do not prove invoice cost.
- The existing process provider supplies exact lease/process identity and positive
  stop proof. Original stop-only cleanup remains available after grants expire;
  cancellation acknowledgement alone cannot release capacity.

## Installation and governed application

An operator installs `ManagedORXSessionProvider` as a compute `RemoteTarget` with a
`ComputePool`. Its underlying provider must launch a task-owned supervisor/harness
with provider access denied until binding. The application uses existing process
tool/environment registrations, `managed_orx_profile.model_registration(targetRef)`,
and an explicit reviewed pricing registration using `request_guard`. The exact
application input schema comes from `exact_input_schema(provider.contract)`.
Ordinary application publication and plan approval remain mandatory.

The contract includes owner, original connection reference/version/revision/hash,
native project ID and identity hash, native session ID, exact profile/hash,
installer revision/enforcement hash and the one-request/text-only limits.
`profile_pin(SessionProfile.options())` converts optional Python options into the
canonical native wire pin. Users cannot supply installation attestations or
replacement contracts through workspace requests.

The independent `read_controls` callback must inspect actual task controls and
return an `AttachmentControlWitness` bearing the opaque, non-serializable
installer-authority token. It must establish:

- Broker-only provider egress and no mounted fallback provider credentials
- Native tools disabled, exact original project/session/profile/connection
- Task-specific process scope and an exclusive original-session lease that also
  prevents concurrent tasks or ungoverned UI turns from sharing this session

The session lease must survive process/controller disconnects until original
custody is proven stopped. A remote JSON or signed self-report is insufficient.
Production operator inspection is a trusted installation prerequisite, not proven
by the synthetic witnesses in tests. Current resource grants/configuration, original
connection grants and live process custody are rechecked on every broker attempt.

`bind_session` installs only this task's ephemeral broker route and returns the
original scoped `OpenResearchSessionHTTP`; it must not itself dispatch a turn.
Optional `observe_session` returns a read-only original-session transport for
restart result recovery without recreating a broker, capability or model request.

## Evidence and recovery

Before sending, the original transcript IDs/leaf are durably recorded. The message
uses one persisted intent and a stable client-turn ID; uncertain acknowledgements
are never replayed. The response artifact requires an exclusive session lease,
exactly one new matching user message under the original leaf, and its completed
assistant child. The acknowledged native turn/session IDs accompany this result.
The public upstream transcript API does not expose its internal turn table, so the
correlation is explicitly labelled `exclusive-original-turn-transcript-delta`.
Unrelated leaves are rejected. Process stop proof is checked independently.

Positive original stop resolves uncertain message *custody* with
`deliveryOutcome=unknown`, not a fabricated success; shared unknown usage remains
held. Native continuation requires an observed response, not just a process receipt.

## Next research capability

Full research requires a separately governed native-tool contract: selected
Factory material/tool adapters, scoped MCP routing, tool-call budget admission,
original child/process custody, safe result provenance and continued model requests
within the same approved ledger. The existing AutoResearch runtime already hosts
five controlled research tools; exposing them to an attached supervisor requires
an explicit compatible tool profile and original-project bindings. Removing the
text-only/request limit without those checks is not a supported implementation.
