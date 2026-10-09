# Ordinary personal commands through native Factory tasks

An operator can install the personal command capability with
`Settings(personal_agent_commands_enabled=True)` and explicitly install the distinct
`opencode-personal-session-v1` provider. Existing verification-only provider registrations
are never upgraded. `publish_application(state, author=..., reviewer=...)` in
`personal_command_profile` publishes the versioned materials/application through normal
independent publication review. It does not create a remote connection, accept a secret,
start a session, or authorize spending. Owner connections remain self-service.

Temporary-plan approval remains the configured Factory policy; it is a separate product
policy decision, not a mandatory property of personal mode. The capability response
reports current policy, and preparation reports exact-plan authorization. This tool is
never classified as read-only, and no endpoint silently approves a plan.

## API

All routes require the authenticated owner and use `/api/factory/personal-agent`:

- `GET /capabilities`: installed contract, actual configured plan policy, advisory budget
  and unverified stop declarations.
- `GET /projects?connectionRef=...`: actual OpenCode project identity and verified connection pin.
- `GET /native-sessions?connectionRef=...`: actual native sessions within the exact project.
- `POST /sessions/attach`: `{requestId, connectionRef, nativeProjectId, nativeSessionId}`.
  Creates/reuses local owner metadata for an existing native session after exact read
  verification. No remote POST, native command task or approval is manufactured;
  `factoryIdentity` is null for a newly attached pre-existing session. Later prompts
  still require normal native command admission. Lost attach acknowledgement is read
  through `GET /requests/{requestId}`.
- `GET /sessions/{id}/rebind-preview?connectionRef=...&expectedOldFingerprint=...`:
  explicitly inspect a replacement owner binding for the same native session. May
  observe an original pending result through the new verified connection but never
  replay its command or silently change the mapping.
- `POST /sessions/{id}/rebind`: `{requestId, connectionRef, expectedOldFingerprint,
  expectedNewFingerprint}`. Both fingerprints must match the reviewed preview.
  Changes only future local session mapping with no capability expansion, under
  exact owner/provider/origin/project/session checks. Unresolved pending work blocks
  the change; prior plan/command/effect attribution remains immutable. The receipt
  has `action: rebind`, `factoryIdentity: null`; recover it through `/requests/{requestId}`.
- `GET /sessions?connectionRef=...`: durable owner sessions.
- `GET /sessions/{id}?refresh=true`: bounded read of original native session messages/tools
  and remote-reported usage. A completed assistant message does not establish process stop.
- `POST /commands/prepare`: `{requestId, action, ...}`. For `create`, specify
  `connectionRef`, `nativeProjectId`, optional `title`. For `prompt`, specify `sessionId`,
  `text`, optional `agent`. For `interrupt`, specify only `sessionId` besides request/action.
  Returns `{plan, authorization, executionContract, commandSuccessMeans, ...}`.
- Normal Factory `/plan-reviews` endpoints handle review when required by current policy.
- `POST /commands/start`: `{planId}`. Uses shared `FactoryAPI.instantiate` with the
  deterministic original task request `personal:{planId}`. Returns the normal Factory job.
- `GET /commands/requests/{requestId}`: read-only lost-ack recovery with
  `{requestId, plan, authorization, job, receipt, nativeRunId}`. Missing task/remote receipt are null.
- `GET /requests/{requestId}`: only the original durable remote command receipt.

Preparation calls governed composition and persisted immutable application inputs. The
connection pin is canonical JSON inside the strict input schema; native execution decodes
it and checks its exact equality to the remote service intent. No endpoint takes remote
URLs, credentials, callbacks, raw provider bodies, unmanaged flags, or alternate models.

## Evidence boundary

The deterministic no-provider Agno model invokes one registered plan-aware tool through
the existing native queue. The tool's trusted closure binds the actual native RunContext,
original plan/task/run, full command, exact connection/project/session, text and generated
correlation IDs. It rechecks current execution authority immediately before dispatch.
The remote model and credentials stay on the user's OpenCode installation.

The shared Factory usage ledger accounts only for the local no-provider controller (zero
provider usage). Remote reported tokens/cost are a separate advisory observation. No
remote compute lease is acquired, no managed stop contract is weakened, and successful
interrupt means accepted best-effort interrupt with stop unverified.

Unknown HTTP acknowledgement remains a durable unknown effect, retaining native command
uncertainty. When an explicit refresh observes the exact original correlated result,
a trusted owner-read callback verifies persisted operation intent, immutable plan,
original task/run and existing effect fingerprint before settling only that command
effect. It never creates an effect, reruns work, proves remote stop, or requires fresh
execution authority merely to observe prior work. Native retry/restart only reads the original remote reservation; it never
resends an unknown operation. A crash between the native effect reservation and remote
reservation also remains unknown. Original native IDs and namespaces are retained. Direct OpenCode sessions are never
represented as native OpenResearch/ORX sessions; explicitly installed native ORX
providers retain their actual native project/session IDs.

## Verification

`test_personal_command_profile.py` covers exact intent/context rejection, independent
registration, strict schema and current permission rechecks. `test_personal_command_postgres.py`
uses real PostgreSQL, the native Agno queue and a controlled local HTTP wire for create,
conversation prompt, unknown acknowledgement recovery and best-effort interrupt. This
fixture must run in the required PostgreSQL CI suite without skips. Local PostgreSQL is
not available in the development workspace; live external OpenCode compatibility remains
unverified. These fixtures are not evidence of real model billing or remote process stop.
