# Owner Chat Completions and OpenCode Go

The owner model settings accept the official Go base URL
`https://opencode.ai/zen/go/v1`, in addition to reviewed HTTPS `/v1`
Chat Completions destinations. No arbitrary provider prefix is accepted.
The owner vault still binds `byok-chat-v1` credentials to the exact HTTPS
origin and revision. Every dispatch rechecks ownership and public DNS, pins the
resolved address with original TLS SNI, and forbids redirects, retries and
environment credential fallback.

This is the text/function Chat Completions subset. Models requiring Responses
or Messages endpoints are unsupported here. Configuration does not invoke a
model, discover models, change account settings, or select a fallback model.
Model names and credentials remain the owner's explicit choices.

The native ORX/OpenCode runtime owns its conversation and tool loop. Its private
broker maps the pinned custom provider's `x-opencode-session-id` to Go's
`x-opencode-session`, and sends an Agent Factory user agent. Conflicting,
missing or malformed session headers fail before external IO.
The independent Agno executor uses its run-scoped owner model instance with a
stable generated conversation ID. Neither path uses the development Go adapter
or a private URL-rewriting test adapter.

Contract reference: [OpenCode Go documentation](https://opencode.ai/docs/go/),
reviewed 2026-10-11. Controlled tests cover official routing, headers, safe
credential custody, native broker HTTP forwarding and ordinary `/v1` behavior.
They establish local behavior, not live Go compatibility.

Native header reference: [OpenCode 1.18.35 request preparation](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/opencode/src/session/llm/request.ts).

The native harness has an outer retry loop in addition to SDK retry settings.
An upstream disconnect or rejected response after possible dispatch ends with
HTTP 422, a sanitized `OWNER_MODEL_CALL_UNCONFIRMED` error and an alphabetic
diagnostic ID. A safely rejected pre-dispatch request ends with HTTP 400 and
`OWNER_MODEL_REQUEST_REJECTED`. No provider exception text or credential is
returned. HTTP 409 is insufficient: the SDK marks it retryable. Diagnostic IDs
also omit numerals because the native policy scans response text for 5xx codes.
See [the pinned native retry policy](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/opencode/src/session/retry.ts).

`scripts/check_owner_model_native_retry.py` runs the pinned 1.18.35 executable
in a fresh container with `--network none` and a synthetic upstream. Both a
disconnect and provider HTTP 502 produce exactly one provider dispatch and a
visible native error. The native retry policy is unmodified. This explicit
offline check requires the installed binary (`--opencode`) and locked container
image digest (`--image`); it neither downloads them nor uses real credentials.

Current limits are historical implementation defaults, not a new billing gate:
64 admitted calls per broker (`OwnerRuntimeBroker.max_calls`) and 4096 output
tokens per forwarded request. The production runtime factory does not expose
an 8-call per-environment override. Its lease/hard deadline and verified
environment stop remain separate from the best-effort native interrupt.

Live acceptance remains pending. A subsequent explicitly authorized bounded
run must save the official URL through the normal UI, use the production pinned
transport without `owner_model_transport_factory`, preserve a native session
header, and verify success, refresh and follow-up in the original ORX runtime.
Failures or unknown acknowledgements must retain their original identity and
must not be replayed to obtain a successful-looking result.
