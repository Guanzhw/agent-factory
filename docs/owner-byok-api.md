# Owner BYOK and disabled Factory billing

Save an owner model, then explicitly select its connection in a published application.
Core uses native Agno execution, immutable bindings and current owner authorization.
The default application catalog is empty. The former Research/ORX application and
its `/personal-research` and `/personal-agent` routes are not installed.

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
  "protocols": ["chat-completions", "responses"],
  "baseURLPath": "/v1",
  "additionalBaseURLs": ["https://opencode.ai/inference/go/v1", "https://opencode.ai/zen/go/v1"],
  "credentialInput": "/api/factory/personal-credentials",
  "credentialUsername": "api-key",
  "platformBillingEnabled": false,
  "hardExternalBudgetEnforced": false,
  "liveCompatibilityVerified": false
}
```

`enabled:false` means the configured vault does not support this provider.
Normal core `Settings.from_env()` startup installs a local encrypted vault with
its persistent key at `FACTORY_WORKSPACE/runtime/credential-vault.key`; back up
that key together with its database. Trusted deployments can override
`Settings.credential_vault_factory`. No model API key or platform-key fallback
is inferred from the environment. The `byok-chat-v1` destination policy binds
credentials to normalized HTTPS origins; provider configuration performs no call.
Model settings do not require publishing an application. Execution does: publish
materials using `owner-chat-completions-v1@1` and declare the model connection
requirement, then supply that exact connection reference at start.

For a generic task in the current UI, open **Developer assembly**, select a
published application whose model material binds `owner-chat-completions-v1@1`,
and select the saved owner's model connection for that application's declared
model requirement. Generate the proposal, confirm the plan, then start the task.
All selected materials must be published; executable bindings must resolve to
installed adapters.
The composer sends explicit `connectionRefs`; choosing a default does not replace
an application's model or automatically select a connection for generic starts.

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
requestId returns the original recorded result; changed
intent returns an idempotency conflict. **API keys belong only to the vault
endpoint**, never to this metadata endpoint. Invalid input responses are redacted.

`GET /personal-models/requests/{requestId}` returns the original owner-scoped
`{ownerId,requestId,action,result,completedAt}` receipt without requiring the old
credential to remain available. It does not submit anything. Read the model list
separately for current status/default: another tab may have changed either since
the original operation. A missing receipt does not prove that an uncertain
request was never sent. See [protocol and recovery boundaries](MODEL_PROTOCOLS.md).

3. `POST /api/factory/personal-models/{reference}/default` with `{requestId}`:
   choose that current owner configuration as the default. Model metadata states
   `configured`, `credential_unavailable`, or `revoked`. `configured` proves
   local custody/scope, not remote provider compatibility or account balance.

Supported protocols are non-streaming text and function tools over
`POST https://host/v1/chat/completions` or `POST https://host/v1/responses`.
Set optional `protocol:"responses"` explicitly; omission and explicit
`"chat-completions"` retain the legacy CC contract and idempotency fingerprint.
HTTPS/443, DNS hostname, exact `/v1` base path (plus the two exact Go prefixes
above), no URL credentials/query/fragment, public DNS/IP checks, pinned address,
original TLS hostname, no redirect, no environment proxy/key lookup, no SDK
retry, bounded body/response sizes, and an async deadline are enforced. Responses
may omit usage; any reported usage is native model metrics, not an authoritative
Factory bill. Responses containing the exact credential are rejected.
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

## Step 2: start the published application

`POST /api/factory/application-interface/v1/starts` (202) accepts the published
application's actual mode and its declared connection name, for example:

```json
{
  "requestId": "owner-application-start-001",
  "application": "your-published-application",
  "mode": "execute",
  "goal": "Run the declared operation",
  "connectionRefs": {"ownerModel": "saved-owner-connection-reference"}
}
```

The identifiers above are placeholders, not an installed application. Core pins
the declared materials and selected connection, persists the original plan/task,
and submits through Agno's native queue. The response contains `interfaceVersion`,
`requestId`, `planId` and `job`. Missing or unavailable required connections block
admission; an unpublished application returns 404. BYOK does not require a host
price or fee review. Current permissions, revocation and task bounds still apply.

An identical request retains its original plan/task; changed intent returns 409.
`GET /api/factory/application-interface/v1/starts/{requestId}` reads its owner-scoped
`planId`, `taskId`, `runId`, `state` and handoff without dispatch; `createsExecution`
and `automaticReplay` are false. Use `/api/factory/jobs/{taskId}` for results.
Recover an UNKNOWN acknowledgement through the original receipt, without changing
the request, model or connection. See [Application Interface](APPLICATION_INTERFACE.md).

## Compatibility and verification

Disabling money management also preserves acknowledged-work inference recovery:
original ownership, cancellation, permission and deadline checks continue without
requiring money scopes. Managed paid profiles remain denied.

`fee_management_enabled=False` leaves existing `af_usage_*` tables, records and
old plan bodies intact; no destructive migration runs. Historical accounting can
be exercised by trusted, explicitly enabled compatibility fixtures. The separate
`platform_paid_models_enabled` also defaults false and requires actual accounting
when explicitly configured. Profiles whose actual model path requires managed
accounting are denied while disabled. Disabling the ledger is not a claim of a
preserved hard budget. Owner BYOK stays outside that ledger even on an enabled legacy host.

Required acceptance: `scripts/check_owner_byok_postgres.py` (required selectors must succeed without skips)
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

Current core-only acceptance must be rerun against the exact revision. Controlled
native execution proves protocol and custody boundaries, not external provider
compatibility, costs or a scientific application. Historical Research behavior is
retained in Git history and the explicitly historical guides.

统一凭据的添加、更换、撤销与显式重新绑定入口见 [个人凭据与连接](PERSONAL_CREDENTIALS.md)。
