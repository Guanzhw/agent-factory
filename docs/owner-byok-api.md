# Personal research: owner BYOK and disabled Factory billing

Backend contract for the two-step journey: save an owner model/default, then
submit a research goal. The backend uses Agno 3.1.0's native Model, tool loop,
durable AgentOS queue, immutable plans, and existing owner authorization.
OpenCode/OpenResearch remote runtimes remain optional, separate integrations.

**Product scope:** `/personal-research` is an optional generic native Agno
template submission service, not the native ORX application. Its bundled
installer is a synthetic literature demo with no internet retrieval or research
experiment. Do not use this endpoint as the default AutoResearch/OpenResearch
product entrypoint or fall back to it when an ORX connection is unavailable.
The existing `/personal-agent/project-commands` and `/personal-agent/commands`
paths retain native ORX project/session execution. This BYOK model registration
does not configure or transfer a key to an ORX remote harness. Actual owner BYOK
integration into that harness/workload and real research tools are not delivered
by this template; native remote compatibility remains unverified.

## Ordinary native ORX owner submission

Use the existing ORX connection/project/session path for the product journey.
After one-time resource setup, daily use is two steps: select the existing
project/session, then enter a goal and Submit. No owner needs to operate
prepare/request-review/admin-decision/start as separate screens.

`GET /api/factory/personal-agent/capabilities` includes
`ownerSubmit:"/api/factory/personal-agent/commands/submit"`,
`modelConfiguration:"remote-configured-model"`, and `factoryBYOKForwarded:false`.
This connection uses the model/account already configured on its remote ORX
harness. The Factory BYOK/default saved below is a separate native Agno binding;
it is not transferred to the remote harness. Model charges may occur on the
remote owner's account; Factory hard external money limits are not enforced.

`POST /api/factory/personal-agent/commands/submit` (202) transparently performs
the existing prepare and start for **one** explicitly submitted business action.
It takes the unchanged prepare schema:

```json
{"requestId":"owner-orx-prompt-001","action":"prompt","sessionId":"personal-session-ref","text":"Investigate this goal on the original ORX project"}
```

`action:"create"` instead takes `{requestId,action,connectionRef,nativeProjectId,title?}`;
`action:"interrupt"` takes `{requestId,action,sessionId}`. This endpoint does not
chain create with prompt, choose a different harness/model, or invent a project.
The response is the existing job shape (`id`, `planId`, status, etc.).
Read `GET /personal-agent/commands/requests/{requestId}` for the persisted
`{requestId,plan,authorization,job,receipt,nativeRunId}` and existing `/jobs/{id}`
for progress/results. An acknowledged command is not a verified scientific result
or remote process stop; the existing native transcript carries observed results.

For an existing native session, the UI can transparently call the existing
read-only `/sessions/attach` while selecting it, then submit the goal once with
`action:"prompt"`. If an existing project needs a new session, one explicitly
labelled "Create session and submit goal" user action may transparently combine
two ordinary owner commands: submit `action:"create"` with a stable
`<journeyId>:create` requestId, recover its acknowledged receipt/native session
identity, then submit `action:"prompt"` with `<journeyId>:prompt` and the returned
Factory sessionId. Each ID must fit the existing 100-character limit. Stop at an
UNKNOWN/missing creation acknowledgment; do not invent an ID or recreate the
session. Recover the prompt request first if its response was lost. The two
commands retain distinct plans/tasks/effects and do not form an atomic workflow;
a crash between them can leave the acknowledged session without a prompt. This
combination uses the owner's native permissions and does not call admin decisions.

Project creation remains a two-step exact owner-consent journey:
`POST /personal-agent/project-commands/prepare` with the existing
`{requestId,connectionRef,project}` returns its immutable preview/disclosure.
After the user sees those writes and possible remote-model charges, a single
explicit confirmation invokes
`POST /personal-agent/project-commands/{requestId}/submit` (202) with
`{previewHash,approved:true}`. The server records that owner's exact consent and
starts the original plan. A wrong hash/owner, cancelled consent, expired binding,
or revoked authority denies dispatch. `approved:false` is not a submit; use the
existing decision endpoint to decline. Existing decision/start APIs remain
compatible and can also be transparently combined after the same owner action.
Connecting the created project retains its existing `/connect` contract and
explicit remote harness/model selection.

The approval shortcut covers owner-created `remote-*` registrations only.
Operator/shared registrations stay under their existing plan review/policy;
the server does not assign an administrator role or submit administrator
decisions on behalf of the user. Shared publication is still independently
reviewed once. Identity, connection revision, organization scope limits, exact
plan/effect hashes, request fingerprints, capacity and cancellation guards remain.

The facade is **not one transaction covering remote side effects**. Plan admission,
owner consent/submission, task reservation and the native effect each keep their
existing durable boundary. A crash after preparation can leave a plan with no
task; GET exposes it without dispatch, and retrying the exact submit can continue
the original admission. The same requestId with changed inputs conflicts. After
a task/effect crosses native or remote submission, a replay uses the original
task/custody and never blind-resends an UNKNOWN remote operation. A lost response
should first be recovered with GET; a revoked/expired original pin still denies
a new execution attempt. Concurrent double-clicks use the existing admission
locks and effects. No extra queue, remote retry or replacement model is added.
The owner-submission row itself is serialized per plan with a PostgreSQL
transaction advisory lock before its existence check/insert. Independent API
workers cannot race that approval before task admission. The required boundary
suite holds the first approval read while a second independent app/worker waits
in PostgreSQL, then verifies both return the original task and one remote effect.

## Setup and capabilities

`GET /api/factory/status` exposes `feeManagementEnabled` and
`platformPaidModelsEnabled`, both **false by default**. No environment or owner
HTTP setting enables platform billing. Factory does not recharge accounts, assign
paid model credit, approve ordinary owner expenditure, or invoice BYOK usage.
External provider charges depend on the owner's provider account. There is **no
Factory hard external money limit**.

`GET /api/factory/personal-models/capabilities` returns:

```json
{
  "enabled": true,
  "providerId": "byok-chat-v1",
  "providers": ["openai", "openai-compatible"],
  "protocol": "chat-completions-text-functions-v1",
  "baseURLPath": "/v1",
  "credentialInput": "/api/factory/personal-credentials",
  "credentialUsername": "api-key",
  "platformBillingEnabled": false,
  "hardExternalBudgetEnforced": false,
  "liveCompatibilityVerified": false
}
```

`enabled:false` means a trusted vault with the `byok-chat-v1` destination policy
has not been installed. There is no default vault encryption key, environment
model API key, or platform-key fallback. Operators reuse
`Settings.credential_vault_factory`, supplying the existing vault's encryption
key through trusted deployment configuration and including `byok-chat-v1` in its
provider destination policies. The standard `origin` policy accepts normalized
HTTPS origins; the adapter additionally resolves and pins only public addresses
for every inference request. No configuration request probes a provider.

`GET /api/factory/personal-research/capabilities` reports
`applicationAvailable`, `applicationId:"personal-research-v1"`, `nativeQueue:true`,
and the model setup path. Shared template/code installation is an administrator
responsibility, performed once; it is not an owner-task approval. The trusted
`personal_research.publish_application(state, author=..., reviewer=...)` installer
uses existing independent material and application publication. Its minimal
bundled literature tools are **synthetic fixtures**, as their evidence states.
It requires the approved research skill/prompt/literature/question/environment
materials; it does not install arbitrary code or silently publish materials.
Production deployments can publish their approved read-only research materials
with the `owner-chat-completions-v1@1` model adapter and a declared owner model
connection. Live provider and real scientific research compatibility remain
unverified.
The bundled demo installer explicitly refuses production (`demo=False`) with
`PERSONAL_RESEARCH_DEMO_TEMPLATE_ONLY`. It is never run automatically at startup.
If a production database retains that synthetic template, capabilities report
`supported:false`, `templateKind:"synthetic-demo"`, and
`unsupportedReason:"PERSONAL_RESEARCH_REAL_TOOLS_REQUIRED"`; submit returns that
409 code before a model/provider call. `applicationAvailable` alone indicates
publication metadata, not actual research support. No synthetic template is
silently selected as an ORX fallback.

## Step 1: save a model and choose the default

The UI can combine the following metadata/secret operations into one Save action.
Each operation keeps its own stable requestId, so an interrupted operation can
be recovered without generating another key or repeating a model call.

1. Existing `POST /api/factory/personal-credentials`: send
   `{requestId,providerId:"byok-chat-v1",destination:"https://host",username:"api-key",password:<user-entered key>}`.
   The vault returns `credentialRef`, `credentialRevision`, provider/destination
   and status only. Its existing `/requests/{requestId}` route recovers the result.
   Errors do not echo request inputs. Credentials are encrypted; secret values
   never become catalog materials, plan content, audit bodies, or API responses.
2. `POST /api/factory/personal-models` (201):

```json
{
  "requestId": "owner-model-save-001",
  "provider": "openai-compatible",
  "baseURL": "https://models.example.com/v1",
  "model": "owner-selected-model",
  "credentialRef": "credential-reference",
  "credentialRevision": "credential-revision"
}
```

The response contains `reference`, `revision`, `connectionRef`, `ownerId`,
`provider`, `baseURL`, `model`, credential refs, `updatedAt`, `status`, `available`,
`isDefault`, and `hardExternalBudgetEnforced:false`. Only authenticated-owner
metadata is listed by `GET /api/factory/personal-models`. Repeating a matching
requestId returns current metadata for the original configuration; changed
intent returns an idempotency conflict. **API keys belong only to the vault
endpoint**, never to this metadata endpoint. Invalid input responses are redacted.

3. `POST /api/factory/personal-models/{reference}/default` with `{requestId}`:
   choose that current owner configuration as the default. Model metadata states
   `configured`, `credential_unavailable`, or `revoked`. `configured` proves
   local custody/scope, not remote provider compatibility or account balance.

Supported protocol is only non-streaming text and function tools over
`POST https://host/v1/chat/completions`. HTTPS/443, DNS hostname, exact `/v1` base
path, no URL credentials/query/fragment, public DNS/IP checks, pinned address,
original TLS hostname, no redirect, no environment proxy/key lookup, no SDK
retry, bounded body/response sizes, and an async deadline are enforced. Responses
may omit usage; any reported usage is native model metrics, not an authoritative
Factory bill. Responses containing the exact credential are rejected. Responses,
Anthropic, multimodal, arbitrary base paths, and arbitrary API compatibility are
not claimed. Native streaming surfaces emit the bounded complete response;
provider SSE streaming is not implemented.

For rotation, call the existing vault
`POST /personal-credentials/{credentialRef}/rotate`, then
`POST /personal-models/{reference}/configure` with the same model configuration
and **new** credential revision/requestId. A new model revision/connectionRef is
created. Old task pins and retained handles fail closed; existing plans are not
rewritten. A selected default continues to refer to this model registration.

`POST /personal-models/{reference}/revoke` with `{requestId}` immediately denies
that model/its retained handles and clears its default. The existing vault
`/revoke` separately revokes the credential itself. Neither operation exposes or
calls the provider. Reads and cleanup remain owner scoped. Another owner's refs
are never valid authority.

## Step 2: submit the research goal

`POST /api/factory/personal-research` (202):

```json
{"topic":"My bounded research question", "requestId":"owner-research-submit-001"}
```

The backend pins the current default owner connection into the approved
`personal-research-v1/literature` template, persists the exact plan and owner
submission, and uses existing Factory instance admission and Agno's native
queue. The response is the existing instance/job shape plus `planId` and:

```json
{"billing":{"payer":"owner-provider-account", "platformBillingEnabled":false, "hardExternalBudgetEnforced":false}}
```

No default returns HTTP 409 with `code:"PERSONAL_MODEL_SETUP_REQUIRED"` and the
settings path in the message. A stale/revoked model denies admission; a missing
approved application is a distinct setup failure. There are no required money
budgets, usage price registrations, fee reviews, or ledger configuration for
ordinary tasks. Computational capacity/tool/time/data limits remain enforced.

Repeating the same requestId retains the original immutable plan/model pin and
original native task. Changed request intent fails. It never selects a different
default to recover the original request.
`GET /personal-research/requests/{requestId}` returns owner-scoped
`{requestId,taskId,planId,nativeRunId,admission}`; it performs no submission.
Existing `/jobs/{taskId}` provides progress, native requirements and results.
Unknown acknowledgements use original custody/recovery, not a new task/model key.

The existing `/instances` and personal `/commands/start` similarly treat the
normal authenticated owner submit as the approval for eligible personal actions.
Preparation/status reports `ownerSubmissionSupported:true`, `reviewRequired:false`,
and `reviewRequestSupported:false` for these scopes, so the UI can show a direct
Start action. `executionAllowed` becomes true after the exact owner submission;
project side effects still require the existing exact owner consent.
Owner submissions bind the exact plan digest; current identity/material/resource
permissions, cancellation, revocation, task depth/capacity and native tool guards
still run. Administrators continue managing shared resources, organization
policy, platform-paid profiles and trusted/shared-definition publication.
Read-only BYOK research and existing owner personal commands qualify; arbitrary
code/writes/shared connections/remote Factory placement do not gain approval.
ORX project creation retains its existing immutable preview/owner consent and
never enables remote clone/model execution merely from configuration. Its UI can
submit the existing exact consent as part of the user's normal business action.

## Compatibility and verification

Disabling money management also preserves acknowledged-work inference recovery:
original ownership, cancellation, permission and deadline checks continue without
requiring money scopes. Managed paid profiles remain denied.

`fee_management_enabled=False` leaves existing `af_usage_*` tables, records and
old plan bodies intact; no destructive migration runs. Historical accounting can
be exercised by trusted, explicitly enabled compatibility fixtures. The separate
`platform_paid_models_enabled` also defaults false and requires actual accounting
when explicitly configured. Profiles whose actual model path requires managed
accounting are denied while disabled, including managed ORX and AutoResearch's
platform-paid profile; disabling the ledger is not a claim of a preserved hard
budget. Owner BYOK stays outside that ledger even on an enabled legacy host.

Required acceptance: `scripts/check_owner_byok_postgres.py` (15 cases, zero skips)
and existing `scripts/check_boundaries_postgres.py`. Supply only an independent,
disposable loopback PG server through `FACTORY_TEST_DATABASE_URL`; fixtures create
and remove their own unique databases. Tests use static synthetic secret fixtures
and `httpx.MockTransport` only. They prove native Agno execution and boundaries,
not real credentials, provider costs, remote research, or deployment readiness.

## Stale browser tabs and account changes

Model settings check the live authenticated session before secret custody and
before each metadata/default/revoke write. Account changes clear the entered
key and model draft and stop the old account's screen. Each vault create,
rotation, recovery and model request also sends `X-Factory-Expected-Owner`.
The existing authenticated identity extractor compares this header with the
verified principal in that same request, before the vault or model service can
write. A mismatch returns 403 `EXPECTED_OWNER_MISMATCH`; the header cannot grant
permissions or choose another account. Existing clients without this narrowing
header keep their authenticated owner contract. The server check covers an
account change between the browser's preflight and its mutation.

The required isolated PostgreSQL regression submits only fake keys using Bob's
verified authentication and Alice's expected owner. It verifies no credential
is created in either account and that model/default/revoke/rotation writes are
rejected. UI regressions cover account changes before saving, between custody
and metadata, and a mismatch returned after preflight. These tests use no real
keys or live provider requests.

This PR completes the current foundation scope: disabled-by-default Factory
billing, owner BYOK for native Agno tasks, owner-scoped resource submission, and
existing native ORX project/session entrypoints. The next application phase can
organize research goals, progress, readable results and user decisions around
actual supplied research data. Structured scientific findings/stages, actual
research tools and real remote/provider compatibility remain undelivered or
unverified; synthetic replies are protocol evidence only.

统一凭据的添加、更换、撤销与显式重新绑定入口见 [个人凭据与连接](PERSONAL_CREDENTIALS.md)。
