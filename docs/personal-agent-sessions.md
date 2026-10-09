# Ordinary personal OpenCode sessions

## Two contracts, separate authority

`opencode-personal-session-v1` is an explicitly installed provider for ordinary
personal execution (`personal-external-v1`). Binding its execution capabilities
is separate from the existing verification-only `opencode-serve-v1` registration.
Existing pins are never upgraded. The model, tools, provider credentials and
billing remain on the remote OpenCode installation. Factory sends only the
owner's approved text and optional existing remote agent name.

There is no boolean that converts a managed plan into an ordinary plan. Managed
supervisor/model-broker budgets and custody remain unchanged. Ordinary cost/token
values are **remote-reported observations**, not trusted metering or enforced
spending limits. An abort response, completed assistant message, or idle session
is not proof that child processes stopped. Interrupt is always presented as
`interrupt_requested_stop_unverified`. This implementation never frees managed
resource leases or marks remote processes stopped.

## Native identities and authorization

The project is a real **native OpenCode project**, not an upstream OpenResearch
project. Session creation persists the actual OpenCode `id` and `projectID` only
after checking the response. All turns use that original remote session; Factory
does not manufacture conversational context or replay past messages. The
projection explicitly leaves `upstreamOrxProjectId` null. OpenResearch full-app
acceptance is separate.

The service requires an operator-provided admission function:

```
admission(owner, immutable_intent) -> {
  planId, taskId, nativeRunId, executionContract: "personal-external-v1"
}
```

Production integration must bind this callback to the real native Factory tool
execution context, verify the immutable approved command and current execution
permission, and reject callers outside it. No HTTP mutation router is provided
by this service. Creating, prompting and interrupting are distinct native
Factory command tasks; the module adds no executor queue. Successful command
acknowledgement does not mean remote inference or compute has finished.

Intent includes owner-scoped connection pin, exact project/session, action,
request ID and text/agent or create title. Generated correlation IDs are bound to
that exact intent. The callback runs before durable reservation and immediately
before the POST; changing its task/run identity fails closed. Current owner
grant, connection state and immutable revision/fingerprint, provider policy,
credential owner/revision/destination and TLS-origin/project identity are checked
at boundaries. Local historical read-only evidence remains available after
revocation; fresh remote access does not bypass it.

## Durable unknown acknowledgements

An independent SQL transaction commits the owner/request intent and native task
identity **before** any POST. Every repeated request returns the prior record,
never automatically re-posts. A lost create acknowledgement cannot be recovered
by guessing a session from its title: the mapping remains unknown. A lost prompt
acknowledgement may be reconciled read-only through the original session's
messages and original client message ID. A later observed assistant result is
recorded with remote provenance. A new prompt is blocked while the original turn
is unresolved. SQL command records are an effect ledger, not a work queue.

The private transport allows only project/session/message reads, session create,
asynchronous prompt and session abort. No authentication installation, provider
configuration, shell, permission response, deletion, redirect or retry path is
available. It reuses reviewed DNS policy, numeric address pinning, TLS certificate
and hostname verification, response size limits and total deadlines. It does not
use proxy/netrc environment credentials.

## API source and verification limits

Official sources checked 2026-10-08:

- https://opencode.ai/docs/server/
- https://github.com/anomalyco/opencode/blob/dev/packages/sdk/js/src/v2/gen/types.gen.ts
- https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/prompt.ts
- https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/id/id.ts

The documented contract uses `POST /session`, `GET /session/:id`,
`GET /session/:id/message`, `POST /session/:id/prompt_async` (204), and
`POST /session/:id/abort`. Native session/message types contain `projectID`,
`sessionID`, `parentID`, completion time, cost and token fields. This is a bounded
client of those documented routes, not a claim that every future version matches.

`platform/tests/test_personal_agent_sessions.py` uses real local HTTP sockets and
a synthetic OpenCode protocol fixture. It covers create, same-session multi-turn
context, tool messages/results, unknown acknowledgements and process restart,
read-only recovery, interrupt, owner/revoke/credential fences, fixed-path denial
and admission changes. The test-only connection seam maps a public synthetic
origin to the controlled loopback server; production policy is not relaxed.
These are controlled protocol tests. No external endpoint, personal credential,
paid inference or real scientific outcome was used or claimed. Production TLS
and actual OpenCode/ORX live compatibility require separate authorized acceptance.

## Shared native-engine ledger

The durable service uses a trusted exact-class provider registry; it does not
accept a caller-supplied engine implementation. The OpenCode engine remains
`environment` / `opencode`. A separately installed native OpenResearch engine
keeps `orx` / `native-openresearch`; its real project/session identities are never
inferred from an OpenCode project.

Existing native sessions can be listed and attached using reads only. Local
attachment creates no artificial Factory execution task; `factoryIdentity` is
null unless the mapping came from an actual Factory create command. Later
prompt/interrupt receipts each carry their own real task/run identity. A canonical
owner/provider/origin/project/session identity index prevents repeated attachments
from bypassing the unresolved-turn fence. Historical command intents and pins
are never changed by another attachment.

An expired, rotated or revoked original connection is not silently replaced.
Attaching the same native identity through a different binding returns
`PERSONAL_CONNECTION_REBIND_REQUIRED`. The explicit rebind preview checks the
expected original fingerprint and a newly verified reference against the same
owner/provider/origin/project/session identity. New capability scope cannot be
wider than the prior mapping. Preview performs only native reads and may recover
the original pending result using the engine's existing correlation rules. An
unknown ORX acknowledgement, queued turn or ambiguous/incomplete result remains
unresolved and blocks rebinding; there is no force-clear override.

Commit requires the exact old and new fingerprints from that preview plus its
own request ID. A compare-and-swap checks the old immutable session-body hash and
an empty active-request slot. It appends old/new pins, request ID and timestamp to
binding history and updates only the connection used by future session commands.
All prior command/plan pins and native task/run identities remain unchanged.
Repeated commit requests recover the same receipt without another mutation.
Authorization, credential and native identity checks run outside the metadata
transaction, including on a real one-connection pool. Session IDs, transcript
context and canonical native identity index do not change. Fresh credential
custody/verification remain separate authorized operations; rebind creates no
credential or model call. Historical local results remain readable while the old
connection is expired, and session projection includes its binding status.

The admission recheck runs again immediately after DNS and credential resolution,
before sending each mutation. A trusted observation callback may reconcile only
the original native task/effect after the durable result observation commits;
it cannot submit a new request. Tool-call message completion timestamps are not
final-turn evidence. OpenCode results require a correlated terminal finish with
no tool parts before another turn is allowed.

OpenCode client message IDs use the upstream timestamp-ordered shape, rather than
random UUID ordering. Client/server clocks should be synchronized, as with native
clients. IDs provide correlation only; they never prove execution or completion.

Successful response JSON is rejected before persistence if it echoes the resolved
service-auth password/token, Basic-auth encoding or full authorization material,
including inside object keys and nested transcript/tool text. The same guard
covers injected trusted test transports. It does not claim to identify unrelated
secrets or arbitrary encodings of remote file contents. Errors remain fixed codes
without the matched value; no partially redacted response is retained.

An interrupt with an unknown HTTP acknowledgement also blocks rebind, even when
there is no active prompt. The existing command ledger is checked under the same
owner lock as the mapping compare-and-swap. Preview returns its exact opaque
request ID and `durable-command-ledger` source. Idle status and transcript content
cannot clear an unknown interrupt. Once its HTTP acknowledgement has returned,
rebind may proceed, but the previously admitted interrupt may still affect the
remote session. Its process-stop guarantee remains unverified.
