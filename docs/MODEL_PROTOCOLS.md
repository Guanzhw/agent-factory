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
provider outputs fail with fixed safe errors. An empty, whitespace-only or
reasoning-only response without a valid tool call is an explicit empty-output
failure, never an empty successful answer. Optional usage is a metric only.

Responses uses `store:false` and carries validated reasoning/function output
items through the associated tool turn. Matching accepts the actual SDK's
`null`/empty tool-message text and equivalent JSON argument serialization;
function names, ordered IDs and JSON values remain exact in meaning, including
the distinction between booleans and numbers. Original provider replay payloads
are preserved. Private continuation data is bound to the original owner,
model/credential revisions, destination, protocol and session.

CC preserves `reasoning_content` privately for every assistant turn that returns
it, including final answers without tool calls. This follows the
[DeepSeek thinking contract](https://api-docs.deepseek.com/guides/thinking_mode/):
requests carrying tools need prior reasoning even from earlier non-tool turns.
It is a generic field contract, with no model-name switch or automatic disabling
of thinking. Provider support for forced tool choice is separate; for example,
DeepSeek documents that forced selection is unsupported while thinking is on.
The adapter does not silently change thinking or retry to obtain an answer.

Agno retains continuation markers in message provider data. The broker keeps
scoped, immutable continuation records: tools are identified by ordered call IDs
and verified message semantics; text-only answers receive separate private
identities even when their visible text is identical. A bounded verified
transcript carries references to these records. Message positions locate a
retained slice but are not continuation identities.

The fixed native client's explicit compaction is a user-only, no-tools request.
Its successful summary retains the parent transcript without discarding any
call receipts. The next request may contain the summary followed by a retained
suffix of that transcript and a new user turn. The complete suffix is checked
against the parent's fixed end, including user/tool messages, so identical
final text with different reasoning maps to the correct original record.
An empty suffix or a suffix starting with an assistant is also supported.
Summary reasoning is restored separately from the retained tail.

Each session/scope reserves its history transition before dispatch; exact
native retries still wait on their existing call receipt. Only one unconsumed
summary is kept. Replacing it with another unidentified summary is rejected,
since the CC wire carries no native summary-message ID. Changed retained
messages, missing records and foreign bindings fail before dispatch. Failed or
UNKNOWN calls do not advance history, erase receipts or trigger resubmission.

**Old CC tool histories without markers, broker restarts and arbitrarily edited
histories cannot be assumed lossless.** Compaction supports an unchanged
retained tail; rewriting old tool results through native pruning is not covered.
No history is deleted, session silently reset, or persistence service added.
Plain text history without tools still works. Responses final-answer reasoning
and summary output items are retained through the same scoped record references;
text-only replay requires an explicit mapped message index, never text lookup.

The base main commit already set `OPENCODE_DISABLE_AUTOCOMPACT=1` in the native
entry environment; this PR did not introduce or change that setting. Native
pruning also defaults off. The new explicit-compaction test uses the real
[fixed native compaction API and conversion](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/opencode/src/session/compaction.ts)
with a nonempty retained tail. Support is implemented in the protocol boundary,
not by relying on disabled automatic compaction; runtime policy remains with
the application assembly owner.

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
The [fixed OpenCode model metadata](https://raw.githubusercontent.com/anomalyco/models.dev/2858118c7109c87cdaaeeb6db35d8e6a10f3ea46/providers/opencode-go/models/deepseek-flash.toml)
marks that alias deprecated and declares `interleaved.reasoning_content`.
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
A continuation must still own its original active setup slot. Even after another
tab checks and removes the archive, a late response cannot recreate the old
setup or send its previously unsent default selection. Only a new explicit user
operation can acquire an empty slot; a late response also cannot report success
after that slot has been released.

## Verification limits

Regression suites use synthetic credentials, temporary SQLite or isolated
PostgreSQL databases, and in-memory provider transports. They exercise both
execution paths, both protocols, function turns, endpoint pinning, original
command results and native non-replay. They do not verify real Go/OpenAI service
behavior, subscription eligibility, billing, or the complete ORX process.

Responses conversion follows the official
[function-calling](https://developers.openai.com/api/docs/guides/function-calling)
and [reasoning](https://developers.openai.com/api/docs/guides/reasoning) contracts,
including reasoning-item continuation with tool outputs. This is a protocol
implementation reference, not evidence of provider parity. Real model acceptance
must be separately arranged by the parent task with approved credentials.

Local validation on 2026-10-13: `npm run check` passed (539 tests, lint,
TypeScript and production build); `npm audit` reported zero vulnerabilities.
Repository Ruff and Pyright passed. The selected Python suites passed 140 tests:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=platform:platform/tests .venv/bin/python -m unittest -v \
  test_model_command_recovery test_model_endpoint_policy test_model_protocol \
  test_model_protocol_execution test_byok_model test_owner_runtime_broker \
  test_trusted_model_proxy test_go_legacy_boundary test_billing_mode \
  test_go_development_profile test_go_luna_output_revision test_execution_bindings
```

PostgreSQL verification uses a disposable loopback-only PostgreSQL 17.11
container, the CI-pinned image digest
`sha256:d74eeac9a635390a49bc21bd49fccd973de707e2a53a76ac49b552b8712ec46f`,
synthetic database credentials, tmpfs data, and a separate `af_test_*` database
per test. No shared database is used. With `FACTORY_TEST_DATABASE_URL` pointing
to that disposable service:

```sh
AGNO_TELEMETRY=false .venv/bin/python scripts/check_owner_byok_postgres.py
AGNO_TELEMETRY=false .venv/bin/python scripts/check_boundaries_postgres.py
AGNO_TELEMETRY=false PYTHONPATH=platform:platform/tests .venv/bin/python -m unittest -v \
  test_model_command_recovery_postgres
```

The owner gate passed 109/109, the boundary gate passed 32/32, and the new
original-result recovery suite passed 15/15, all with zero skips.
Those PostgreSQL runs covered `e1ac87d`; the later compaction follow-up changes
the broker and offline regressions, without changing the model command service
or database contract. They are not represented as reruns on the later head.
For the initial head `19ca4d532c926c1db59f8efccd21e955bc7b1581`, the
[PR PostgreSQL job](https://github.com/Guanzhw/agent-factory/actions/runs/38383491119/job/115249437827)
and [push PostgreSQL job](https://github.com/Guanzhw/agent-factory/actions/runs/38383467044/job/115249354831)
completed all five required zero-skip gates (109 owner, 32 boundary, 9 candidate,
11 AutoResearch and 10 workflow cases). Their full PostgreSQL suite was still
running when checked at 10:51 UTC; that is not a full-CI success claim or evidence
for a later commit.

Actual OpenCode 1.18.35 binary acceptance passed 8/8 cases: upstream disconnect,
502, lost downstream response, two user turns, CC tools, Responses tools, and
explicit compaction followed by tools for both protocols.
Both tool cases executed the real native `read` tool twice. CC additionally
continued the same native session and restored all three prior reasoning fields,
including the final answer. The first three failure/recovery cases each made
exactly one synthetic provider dispatch. Containers used `--network none` and
the production broker with an injected upstream `MockTransport`.

Two further cases invoke the actual native session `summarize` API with
`auto:false`, then continue with two more real file reads. The fixture retains
one recent user turn. Two pre-compaction final answers have identical visible
text and different private reasoning; the CC case checks that only the retained
answer's reasoning returns, alongside the summary and new tool continuations.
The Responses case applies the same strict check to encrypted reasoning items.
The native persisted compaction marker, summary assistant and nonempty
`tail_start_id` are inspected through the native session API. No model request
is manually rewritten to simulate compaction. The fixture's tail selection is
temporary and does not change the production entry or safety settings.

```sh
.venv/bin/python scripts/check_owner_model_native_retry.py \
  --opencode /path/to/opencode-1.18.35-baseline \
  --image sha256:09fac22af2fd4a25594a5b259f918e1a2b77cb15b00b21db260487f1cfcf8503
```

The binary SHA-256 is
`77b2cfe4b97df6f15c3673b22100b9f79c711f25ecb9bf513bb82526b15d24fa`.
The image is the local immutable image ID for the repository's pinned
`python:3.12.14-trixie` runtime; see [runtime provenance](ORX_BUILD_PROVENANCE.json).
The script checks the binary hash and requires an immutable local image ID.

A separate actual `ai.streamText` SDK test passed 3/3 scenarios: CC tool turns,
Responses tool turns, and a CC final answer followed by a user/tool turn.
It uses `@ai-sdk/openai-compatible@2.0.41`, `ai@6.0.168`, `zod@4.1.8` and the
[OpenCode v1.18.35 SDK patch](https://raw.githubusercontent.com/anomalyco/opencode/53d1eabb61e21162157817bf677da0a4ad3332e3/patches/@ai-sdk%252Fopenai-compatible@2.0.41.patch).
The test verifies exact package versions and patched SDK entry hashes, then
routes the actual SDK's fetch only through the broker's Unix socket. It asserts
the SDK's real `null` to empty-text conversion and JSON argument reserialization;
passing copied broker responses would not pass these checks.

```sh
# Prepare a separate temporary SDK directory; no application dependencies change.
npm install --prefix /tmp/owner-model-sdk --no-save --ignore-scripts --no-audit --no-fund \
  @ai-sdk/openai-compatible@2.0.41 ai@6.0.168 zod@4.1.8
curl --fail --silent --show-error \
  'https://raw.githubusercontent.com/anomalyco/opencode/53d1eabb61e21162157817bf677da0a4ad3332e3/patches/@ai-sdk%252Fopenai-compatible@2.0.41.patch' \
  -o /tmp/owner-model-sdk/openai-compatible.patch
patch -d /tmp/owner-model-sdk/node_modules/@ai-sdk/openai-compatible -p1 --forward \
  -i /tmp/owner-model-sdk/openai-compatible.patch
.venv/bin/python scripts/check_owner_model_native_protocols.py --sdk-root /tmp/owner-model-sdk
```

The real native executable and SDK tests are offline protocol acceptance, not
complete ORX or live-provider acceptance. No provider credential was read or
created, and no real inference request was sent. A compact
[acceptance record](evidence/owner-model-protocols-offline-2026-10-13.json)
includes exact tested file hashes, binary/image pins and individual results.
