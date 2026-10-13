# Owner model boundaries and compatibility

This change keeps two execution paths. Agno uses `OwnerChatModel` and its native
tool loop. The native ORX runtime uses its existing OpenAI-compatible local
Chat Completions route to `OwnerRuntimeBroker`. Only the broker's upstream wire
protocol changes with owner configuration; ORX does not receive the owner's key.

| Responsibility | Existing or shared boundary |
| --- | --- |
| Owner authorization, model/credential revisions, destination binding | `PersonalModels`, vault and connection services |
| Agno messages and tool lifecycle | `byok_model.py` |
| Native runtime scope, original call receipts, UNKNOWN recovery | `owner_runtime_broker.py` |
| Text/function request and response conversion | Pure `model_protocol.py` |
| Reviewed URL prefixes, Go session headers, legacy model option | Small `model_endpoint_policy.py` |
| Public DNS pinning, TLS hostname, response size/secret-echo checks | `model_transport.py` |
| Explicit UI presets and legacy metadata validation | `web/modelProviderConfig.ts` |

Constructors, router mounting, credential provider `byok-chat-v1`, material adapter
`owner-chat-completions-v1@1`, and `ModelSettings` props stay compatible. No new
provider registry, secret store, table, queue, cost limit or application assembly
is introduced. The adapter's historical name remains an immutable identifier.

## Protocol selection

New metadata accepts `protocol: "chat-completions" | "responses"`. Missing means
CC; an explicit CC value is normalized to omission for old command fingerprints.
Explicit null and unknown protocols are rejected. Responses is always explicit,
including for an unfamiliar model name. Public APIs contain no model-to-protocol
switch. Both codecs support bounded text and function tools; function IDs,
arguments, tool choice and token limits are mapped. Invalid/incomplete/refused
provider outputs fail with fixed safe errors. Optional usage is a metric only.

Responses uses `store:false` and carries validated reasoning/function output
items through the associated tool turn. Private continuation data is bound to
the original owner, model/credential revisions, destination, protocol and session.
Agno retains it in message provider data; the broker retains it within the existing
scoped broker lifecycle. Missing or mismatched tool continuation fails closed.
There is no general conversation store or guarantee of reasoning continuity
across unrelated user turns or broker restarts. The original native call receipt
and UNKNOWN rule still prevent blind provider resubmission.

Transport remains HTTPS/443 with public DNS checks on each request, connection
to the checked address, original Host/SNI and certificate verification. No
arbitrary paths, headers, environment proxies, redirects or automatic retries
are added. An existing trusted gateway grant remains restricted to its exact
legacy Go CC route and original owner/model/credential revisions; it cannot
authorize Responses or the new Go prefix.

## Go and historical configurations

The [official Go endpoint and client requirements](https://opencode.ai/v2/docs/console/go/#endpoints)
were read on 2026-10-13. The UI offers two explicit presets:

| HTTP model | Protocol | Base URL |
| --- | --- | --- |
| `gpt-6-luna` | Responses | `https://opencode.ai/inference/go/v1` |
| `deepseek-flash` (displayed by Go as DeepSeek V4.1 Flash) | Chat Completions | `https://opencode.ai/inference/go/v1` |

Native catalog identifiers (`opencode-go/gpt-6-luna` and
`opencode-go/deepseek-v4.1-flash`) are distinct from the HTTP model values.
The endpoint table currently names `deepseek-v4.1-flash`; the
[legacy public model catalog](https://opencode.ai/zen/go/v1/models) also lists
`deepseek-flash`. The latter remains the requested HTTP alias in the preset.
Its presence in that catalog does not verify inference on the new prefix.
Go requests include the application's User-Agent and stable conversation header.
Generic public HTTPS `/v1` providers remain configurable without Go headers.

Stored `/zen/go/v1` configurations retain that exact base URL. No record is
deleted, rewritten or silently upgraded, and a readable legacy model catalog
does not prove old inference is equivalent to the new endpoint. LongCat is not a
preset or preferred execution fixture. Its historical `thinkingMode` metadata
remains readable and the existing disabled-thinking option applies only to its
original model, old Go prefix and CC protocol. Changing endpoint/protocol is a
new explicit configuration revision; old plans remain pinned to their original
binding. No new LongCat-specific public field is introduced.
An existing saved default is not silently switched to another model; its owner
can explicitly select a replacement. No model is automatically chosen by name.

Historical Go development campaigns remain compatibility modules with their
existing gates and records. Ordinary model dispatch/connection checks use a
small legacy identifier module and load campaign preflight only for the exact
legacy path. This does not claim removal of historical app installers from the
main composition root, which is maintained by the separate application branch.

## Interrupted settings operations

The model command table already stores immutable results. Same-intent POST
replay and the new read-only `GET /personal-models/requests/{requestId}` return
that original result. The current list remains the authority for current
availability/default. GET is owner scoped, requires read authority, is marked
`no-store`, and does not resolve a key or require an old credential to stay active.

The UI persists each stage's dispatch marker before its POST. A restored or
uncertain stage recovers its original request ID using GET; it does not send the
POST again. An unsent next stage may proceed after the preceding receipt is
known. Older saved setup records without markers are conservatively treated as
already sent. A definitive initial 403/422 releases the setup form; a 403 during
recovery cannot erase uncertainty about an earlier committed operation.

Users can leave an uncertain setup to continue other work. Its secret-free
metadata is archived under the same owner for read-only receipt checking. This
does not revoke resources, resend requests, or claim the operation failed.
Credential UNKNOWN remains on the existing credential GET recovery path.

## Verification limits

Regression suites use synthetic credentials, temporary SQLite where applicable,
and in-memory provider transports. They exercise both execution paths, both
protocols, function turns, endpoint pinning, original command results and native
non-replay. They do not verify real Go/OpenAI service behavior, subscription
eligibility, billing, native ORX deployment, or PostgreSQL concurrency.

Responses conversion follows the official
[function-calling](https://developers.openai.com/api/docs/guides/function-calling)
and [reasoning](https://developers.openai.com/api/docs/guides/reasoning) contracts,
including reasoning-item continuation with tool outputs. This is a protocol
implementation reference, not evidence of provider parity. Real model acceptance
must be separately arranged by the parent task with approved credentials.

Local validation on 2026-10-13: `npm run check` passed (537 tests, lint,
TypeScript and production build); `npm audit` reported zero vulnerabilities.
Repository Ruff and Pyright passed. The selected Python suites passed 120 tests:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=platform:platform/tests .venv/bin/python -m unittest -v \
  test_model_command_recovery test_model_endpoint_policy test_model_protocol \
  test_model_protocol_execution test_byok_model test_owner_runtime_broker \
  test_trusted_model_proxy test_go_legacy_boundary test_billing_mode \
  test_go_development_profile test_go_luna_output_revision test_execution_bindings
```

No disposable PostgreSQL service was available for the existing PostgreSQL
boundary suites. No provider credential was read or created, and no real
inference request was sent.
