# Ordinary OpenResearch research journey

The ordinary application now starts from a research goal and optional pasted text or links. With a usable personal project binding and its verified remote session template, **Start research** creates one original native session, waits for its acknowledged ID, then submits the authorized goal on the existing personal-command/Agno queue path. Continuing submits to the same native session. Factory does not install a runtime, run a second research engine, download supplied links, or forward its BYOK model credentials to ORX.

The main view projects only observed command/session states and native replies. It never infers scientific stages, percentages, successful research conclusions or confirmed remote termination. Tools, raw outputs, command identities, binding renewal and task/artifact inspection remain available in details. Empty replies and unknown acknowledgements do not produce substitute results. A provisional `ack_unknown` while the original native task is running retains the in-memory authorized follow-up; a terminal unknown stops the follow-up without replaying creation or adopting another session. Original-request recovery adds an optional `nativeStatus` observation from the actual queue/run snapshot: Factory status can remain `unknown` after the native command finishes because its remote effect is unresolved; this field is not a remote-stop or research-success claim.

Goal/material drafts are isolated by owner in browser session storage. Durable local command pointers contain only opaque IDs. Navigation/reload restores drafts and original session selection, but never automatically resends a goal lost with an in-memory continuation. Mutating journey submissions send the expected-owner hint; changed or expired identities clear the visible draft before further dispatch. Existing server owner/capability/current binding checks remain authoritative.

## First connection

Configuration stays in the research workspace and reuses the existing personal service credential/configure/verify/bind controls. Existing compatible bindings are selected automatically. A separately authorized project-list/create connection can list actual upstream projects by name; explicitly choosing a project performs authenticated **GETs only upstream**, configures the owner-scoped binding and chooses a real nonarchived session with an explicit remote model as the new-session template. No invented template, model key, harness or project ID is used. Intermediate/final setup receipts reuse existing stores; uncertain setup is recovered by reading the final original bind receipt, never by repeating its POST. Shared or task-scoped grants cannot be converted into owner-owned submission access by this selection operation.

The bounded additive HTTP endpoints are:

- `GET /api/factory/personal-agent/project-selection?connectionRef=...`: actual project metadata using the existing authorized creation/list binding.
- `POST /api/factory/personal-agent/project-selection`: `{requestId, connectionRef, nativeProjectId}`; explicit personal project binding, read-only upstream validation and reuse of a real remote session template.
- `GET /api/factory/personal-agent/project-selection/requests/{requestId}`: owner-scoped final bind receipt only. A missing receipt does not prove that intermediate setup was absent.

Creating a completely new upstream project remains a separate disclosed operation: upstream 0.2.13 requires an authorized absolute remote path, and native session creation requires an explicit model-bearing template or configured defaults. The current protocol cannot safely supply those for an empty service. The workspace therefore retains the existing creation/clone preview and owner-consent flow in **New remote project**, preserves the goal draft, and states the missing configuration. It does not claim empty-service two-action setup, silently create/clone resources or use a synthetic replacement. Project creation can request remote model suggestions and incur the remote account's charges; its existing disclosure and exact consent remain intact.

## Verification scope

Controlled tests use fake credentials, the pinned ORX wire shapes, a supported isolated PostgreSQL fixture and actual Agno native queue, plus real Chromium desktop/390px pixel inspection. They verify configured start/result/continue, first configuration/draft retention, owner isolation, repeated clicks, original receipt recovery, navigation, empty observations and unavailable upstream. The new PostgreSQL journey case is included in the mandatory boundary gate (20 cases, zero skips).

This verifies application/protocol wiring, not a paid model, installed live ORX runtime, original research tools, scientific results, generic artifact export or complete managed multi-step guarantees. Controlled AutoResearch training fixtures, checksum and managed text probes remain separate optional entry points.
