# Ordinary native OpenResearch sessions

Provider `openresearch-personal-session-v1`, connection kind `orx`, and namespace
`native-openresearch` use real OpenResearch project/session APIs. They do not
rename OpenCode IDs or imitate an ORX project, transcript, playbook or agent loop.
The implementation targets upstream revision
`f336b121525d99364e2dee4fe90b2784894a54e6`, version 0.2.13/dashboard protocol 2.
Remote version/instance values remain remote-reported, not binary attestation.

## Normal path

1. Configure an HTTPS origin, the owner's destination-bound service credential
   reference/revision, and the existing native project ID.
2. List that project's actual native sessions and attach the selected original ID.
   This writes local ownership/command mapping only, without creating anything
   upstream. The native harness/model/default selection remains upstream-owned.
3. Explicit user prompts invoke the original native session. ORX owns its agent
   and tool loop. Refresh displays bounded native text and tool results.
4. A later explicit user prompt continues the same native session. Interrupt sends
   the actual upstream interrupt request; it does not certify process termination.

The same durable ordinary-command service, native Factory admission and original
request recovery are used for OpenCode and ORX. Engine adapters keep their native
identities, routes and wire shapes separate. No second execution queue or
Factory-owned inference loop is introduced.

## Credentials and guarantees

`authMode` is explicit:

- `bearer`: the vault password value is the native ORX remote **service token**;
  the username field is unused and may be labelled `bearer` by the secure form.
- `basic-proxy`: the vault username/password authenticate the user's HTTPS reverse
  proxy in front of ORX.

These are remote-service credentials, not shared Factory model keys. Model
credentials, permissions, tool execution and billing remain on the user's remote
runtime. Ordinary mode reports advisory budgets, unavailable/remote-reported usage
and unverified stop status. A context-window occupancy count is not metered usage.
Managed workload enforcement is unchanged and is not silently weakened by this
separate contract.

Both modes reuse the allowlisted pinned-IP HTTPS transport: current owner and
credential revisions, DNS/SSRF policy, TLS hostname validation, bounded body/time,
no redirects or retry middleware. Exact original Factory admission is rechecked
after DNS/credential retrieval immediately before every mutation. Only the fixed
project/session endpoints are allowed; no shell, file, credential, permission-
approval or playbook mutation route is exposed. Existing project-bound connections
still reject project creation; a separate explicit creation-only connection and
owner-approved plan enable the narrowly scoped project POST.

## Creation and acknowledgement handling

Existing-session attachment needs no model configuration. Optional
`sessionTemplateId` permits creating a new session from that actual existing
session's explicit harness/model/options. Remote-default models are valid for
attachment but cannot silently become a new explicit creation choice. Title
updates are separately labelled unconfirmed if their acknowledgement is lost;
an acknowledged created session is retained rather than created again.

An explicitly created project's new connection may instead pin `sessionDefaults`
with an owner-selected harness/model for its first session; no template is required
then. This does not change existing template-only configurations.

[Ordinary native project creation](PERSONAL_OPENRESEARCH_PROJECT_CREATION.md)
has a versioned source/remote-write/model-cost preview and per-request server-side
consent, followed by existing plan review/native task admission. Upstream starts
conditional background chat-suggestion generation, which may make a model call.
GitHub synchronization is explicitly disabled. Ordinary session prompts may
also cause upstream-owned auxiliary/model/tool work; this adapter claims no hard
spending or process-stop enforcement.

Unknown create/message acknowledgements remain unknown and are never resent or
adopted from similar content. Upstream messages expose parent/leaf metadata but no
public read-only turn-to-message table. A queued acknowledgement carries a client
turn ID, not an authoritative native turn ID; it is not relabelled.

For an acknowledged nonqueued turn only, continuation may become available from
a conservative **remote-reported inference**: the ordered pre-submit message IDs
and content hashes remain intact, exactly one matching new user message and its
completed assistant child appear, and the remote session is idle with no queued
turns. Pending tools/prompts, changed history and concurrent/ambiguous deltas remain
blocked. The observation is labelled `inferred-transcript-delta`, with
`exactTurnVerified=false`, `stopVerified=false` and no scientific verification.

## Evidence

Controlled tests exercise the native wire contract with the actual shared
connection/command persistence service. They do not prove a live ORX server,
remote model execution, external service credentials or scientific results.

Source: pinned upstream [routes and session handlers](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/commands/up.rs),
[native message/turn semantics](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/local/chat/mod.rs),
and [remote dashboard bearer authentication](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/commands/up_remote.rs).
