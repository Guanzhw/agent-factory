# Ordinary OpenResearch research journey

The ordinary application now starts from a research goal and optional pasted text or links. With a usable personal project binding and its verified remote session template, **Start research** creates one original native session, waits for its acknowledged ID, then submits the authorized goal on the existing personal-command/Agno queue path. Continuing submits to the same native session. Factory does not install a runtime, run a second research engine, download supplied links, or forward its BYOK model credentials to ORX.

The two core actions are goal entry and **Start research**, from an already-open, configured OpenResearch view without a selected research. Entering from the application catalog adds one action, and login adds another. Optional materials add opening the field and entering text. When a previous research is selected, the form explicitly says **Continue research**; **Start a new research** clears that selection before creating a separate native session.

The main view projects only observed command/session states and native replies. It never infers scientific stages, percentages, successful research conclusions or confirmed remote termination. Tools, raw outputs, command identities, binding renewal and task/artifact inspection remain available in details. Empty replies and unknown acknowledgements do not produce substitute results. A provisional `ack_unknown` while the original native task is running retains the in-memory authorized follow-up; a terminal unknown stops the follow-up without replaying creation or adopting another session. Original-request recovery adds an optional `nativeStatus` observation from the actual queue/run snapshot: Factory status can remain `unknown` after the native command finishes because its remote effect is unresolved; this field is not a remote-stop or research-success claim.

Goal/material drafts are isolated by owner in browser session storage. Durable local command pointers contain only opaque IDs. Navigation/reload restores drafts and original session selection, but never automatically resends a goal lost with an in-memory continuation. Mutating journey submissions send the expected-owner hint; changed or expired identities clear the visible draft before further dispatch. Existing server owner/capability/current binding checks remain authoritative.

## First connection

Configuration stays in the research workspace and reuses the existing personal service credential/configure/verify/bind controls. Existing compatible bindings are selected automatically. A separately authorized project-list/create connection can list actual upstream projects by name; explicitly choosing a project performs authenticated **GETs only upstream**, configures the owner-scoped binding and chooses a real nonarchived session with an explicit remote model as the new-session template. No invented template, model key, harness or project ID is used. Intermediate/final setup receipts reuse existing stores; uncertain setup is recovered by reading the final original bind receipt, never by repeating its POST. Shared or task-scoped grants cannot be converted into owner-owned submission access by this selection operation.

The bounded additive HTTP endpoints are:

- `GET /api/factory/personal-agent/project-selection?connectionRef=...`: actual project metadata using the existing authorized creation/list binding.
- `POST /api/factory/personal-agent/project-selection`: `{requestId, connectionRef, nativeProjectId}`; explicit personal project binding, read-only upstream validation and reuse of a real remote session template.
- `GET /api/factory/personal-agent/project-selection/requests/{requestId}`: owner-scoped final bind receipt only. A missing receipt does not prove that intermediate setup was absent.
- `GET /api/factory/personal-agent/project-selection/requests/{requestId}/status`: owner-scoped configuration-selection receipt, distinguishing a terminal rejection, saved partial local configuration, an unknown result and a completed binding. Known failures permit a new explicit selection; unknown results permit leaving while retaining the original browser pointer for read-only reconciliation. Neither recovery path replays configuration or credentials, sends a research goal, nor treats a single missing receipt as nonexecution.

Creating a completely new upstream project remains a separate disclosed operation: upstream 0.2.13 requires an authorized absolute remote path, and native session creation requires an explicit model-bearing template or configured defaults. The current protocol cannot safely supply those for an empty service. The workspace therefore retains the existing creation/clone preview and owner-consent flow in **New remote project**, preserves the goal draft, and states the missing configuration. It does not claim empty-service two-action setup, silently create/clone resources or use a synthetic replacement. Project creation can request remote model suggestions and incur the remote account's charges; its existing disclosure and exact consent remain intact.

## Continuing after verification expiry

The 15-minute runtime verification TTL remains unchanged. Opening an expired,
configured project can internally recheck its health and derive a binding with
exactly the original capabilities. Continuing an expired research uses the same
native session: an explicit new **Continue research** submission performs the
bounded health check and guarded local rebind before admitting that new command.
**Continue viewing research** performs this check without sending any goal.
There is no routine verify → bind → rebind configuration sequence for unchanged
owner credentials and targets.

Renewal first proves the original immutable configuration, credential revision,
provider policy and capability scope, using the existing connection command
ledger. Revocation, rotation, changed origin/project/template or changed policy
requires explicit selection. A failed health check can retry only under a
previously saved same-scope renewal proof. Owner grants and current bindings are
rechecked; no expired handle is used. Health verification is GET-only. An
unresolved original turn or unknown interrupt blocks migration; reading its
original observation never resends it. Original plans, tasks, effects, session
identity and command snapshots remain unchanged. A replayed command request
uses its original plan rather than substituting a newly refreshed binding.

Derived binding insertion atomically checks the exact verified revision and
fingerprint whose service identity matched the original proof, then checks that
identity again under the final owner lock. A concurrent verification cannot
substitute a new service identity. Only the explicit pre-admission lease rejection
codes unlock the research draft for a new connection selection; other HTTP409
responses retain the original request pointer and never imply nonexecution.
`REMOTE_VERIFICATION_FAILED` becomes `ORX_LEASE_PRE_ADMISSION_HEALTH_CHECK_FAILED`
only in the lease-check phase before plan admission; the raw code remains ambiguous.
A temporary health failure preserves the goal and
allows an explicit new retry after recovery; it never replays the failed request.

- `POST /api/factory/personal-agent/connections/{ref}/refresh`:
  `{expectedFingerprint}`; same-owner/same-scope local lease maintenance only.
- `POST /api/factory/personal-agent/sessions/{id}/continue`:
  `{expectedFingerprint}`; returns current session and `ready`, `waiting` or
  `unavailable`; does not create projects/sessions or send/interrupt research.

## Verification scope

Controlled tests use fake credentials, the pinned ORX wire shapes, a supported isolated PostgreSQL fixture and actual Agno native queue, plus real Chromium desktop/390px pixel inspection. They verify configured start/result/continue, first configuration/draft retention, owner isolation, repeated clicks, original receipt recovery, navigation, empty observations and unavailable upstream. The PostgreSQL journey and configuration recovery cases are included in the mandatory boundary gate; required CI rejects every skipped case.

This verifies application/protocol wiring, not a paid model, installed live ORX runtime, original research tools, scientific results, generic artifact export or complete managed multi-step guarantees. Controlled AutoResearch training fixtures, checksum and managed text probes remain separate optional entry points.
