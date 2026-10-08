# OpenCode Go development adapter — prior isolated stage

**Superseded scope:** the next stage now supplies an explicit Factory development
registration and controlled HTTP/PostgreSQL product-path tests. See
[development product profile](GO_DEVELOPMENT_PROFILE.md) for current setup and
gates. The historical isolated-stage claims below are retained as provenance;
“unregistered” and missing request-guard statements no longer describe the fixture
profile. Live subscription execution remains blocked.

`agent_factory.opencode_go.GoDevelopmentModel` is an unregistered development
adapter for ordinary coding-agent integration tests. Importing or constructing it
reads no environment variables, discovers no credentials and opens no network
connection. It does not change production model bindings, platform defaults,
account settings or the dependency lock.

## Public contract checked on 2026-10-02

The [official Go documentation](https://opencode.ai/v2/docs/console/go) specifies
coding-agent traffic, an honest client User-Agent, and a stable
`x-opencode-session`. Its endpoint table maps versioned DeepSeek Flash models to
Chat Completions and GPT 6 Luna to Responses, under
`https://opencode.ai/zen/go/v1`. Its balance option can enable paid fallback after
subscription limits. No request-level subscription-only switch was established.

The [public model catalog](https://opencode.ai/zen/go/v1/models) was readable via
the research browser. It contains `deepseek-flash`, `deepseek-v4-flash`,
`deepseek-v4.1-flash`, and `gpt-6-luna`, but does not resolve the alias target.
The adapter rejects `deepseek-flash`; choosing an exact version is a separate
operator decision. A direct unauthenticated Python GET received HTTP 403 in this
workspace; no bypass was attempted. Neither observation proves inference access.

## Implemented boundary

Only three exact model IDs are accepted: `deepseek-v4-flash`,
`deepseek-v4.1-flash`, and `gpt-6-luna`. Endpoint, own User-Agent, and header names
are fixed in code. The stable conversation identity is an opaque 8–128 character
operator-provided session ID; it must not be a person's name or credential.

The trusted construction interface accepts a credential callback and a
`billing_verified(session_id, model_id)` callback. Every invocation verifies
billing **before** calling the credential callback. A missing, false, or failing
verifier fails closed. This is an integration boundary, not verification of
account settings: accepting a prompt-supplied boolean or installing
`lambda *_: True` in a real binding would violate the contract. Test fixtures use
that callback only alongside `httpx.MockTransport` and synthetic credentials.
The operator verifier must be current, account-specific, independent of model
input, and confirm subscription-only authorization with balance fallback disabled.
There is no production verifier or registration in this change.

The adapter sends one HTTP request per native invocation. HTTP redirects, ambient
proxy/config discovery, and network retries are disabled. No tools are executed
inside the adapter. Native Agno may call again after an independently authorized
tool result; existing Factory admission/current-authority/ledger guards must wrap
every such invocation. Live development approval is separately limited to three
short requests per model; this adapter does not grant or count that authorization.

Both native sync and async methods use the async HTTP transport and a total
`asyncio.timeout` deadline, default 30 seconds and maximum 60. Sync methods bridge
through one short-lived thread, including when called from an existing event
loop. Credential and billing callbacks are trusted local callbacks and must not
perform blocking I/O. Default output limit is 256 tokens, maximum 512. Request and
response payloads are bounded to 1 MiB. Native structured outputs, multimodal
messages, built-in provider tools, and named forced-tool choices are unsupported.

Streaming is deliberately **bounded buffered SSE**: one native result is emitted
after a terminal provider event. Chat tool-name/argument fragments are assembled;
Responses uses its completed response's full output. Partial tool JSON never
executes, and incomplete/cancelled streams expose no final usage. This is not
progressive token display. Errors expose a fixed message and status code without
server bodies, headers, credential values or chained exception text.

Authoritative nonnegative integer input/output/total token counters populate
Agno `ModelResponse.response_usage` only when totals reconcile. Existing
`native_response_usage` can read them. Missing/inconsistent counters, incomplete
responses and transport failures provide no usage evidence; the Factory ledger
must keep its UNKNOWN hold. This does not establish prices, cached-token tariffs,
subscription availability or account charge amounts. A separate immutable
operator pricing policy is required before a real registered model binding.

## Validation and remaining gates

```sh
PYTHONPATH=platform .venv/bin/python -m unittest discover -s platform/tests -p test_opencode_go.py -v
.venv/bin/ruff check platform/agent_factory/opencode_go.py platform/tests/test_opencode_go.py
.venv/bin/pyright platform/agent_factory/opencode_go.py platform/tests/test_opencode_go.py
```

24 offline tests cover native Agno sync response and streaming, async transport,
endpoint/header/session contracts, tool round-trip encoding, fragmented tool SSE,
Responses completion, terminal usage, UNKNOWN evidence, total deadline
cancellation, size bounds, unsupported alias/budget rejection, billing-before-key
ordering, credential-error redaction, and non-retried 302/401/402/429/503 handling.
The real `DelegatingModel._guard_provider_calls` wrapper is exercised against
all four public invocation methods, with successful, HTTP 503, missing-usage,
timeout, incomplete-protocol and premature-stream-usage mock responses
(twenty-four subcases): each performs
exactly one HTTP request, one
admission callback, and one settlement callback. Failed attempts pass no usage
evidence; missing usage also passes no evidence. Cancellation during actual mock
body iteration is covered for both async methods: the transport closes, one
settlement receives no evidence, and cancellation propagates. Parsers reject
duplicate tool identities, ambiguous choices, premature or repeated stream usage, invalid tool
indexes and choices after a terminal finish reason, preventing a truncated
completion from being rewritten as successful. Chat usage is accepted only after
the terminal choice, including a terminal choice in the same event. The four
methods share a private HTTP entrypoint; sync-to-async bridging
never invokes another ledger-wrapped public method. The ledger itself is a
lightweight recorder in these tests; this is not a new PostgreSQL acceptance run.

No real key was read, no authenticated request was made, and no model ran.

Remaining gates: a trusted subscription-only billing verification mechanism;
root-owned credential availability; exact requested Flash model decision; native
Factory registration with immutable pricing/current-authority/usage bindings;
and a separately bounded live coding test proving actual wire compatibility.
Go does not become an approved non-coding research provider through this adapter.
Production provider choice and production credentials remain independent.

## Registration boundary not implemented

The existing `Settings.runtime_adapters` and `Settings.usage_pricing` hooks can
install a development-only registration without changing the shared dispatcher.
A fresh factory per exact model/revision must derive session identity from trusted
`BindingContext.run_context`, with billing/credential callbacks retained in
operator code or trusted connection handles. Material configuration cannot supply
those callbacks, verification flags, provider endpoints, retries or credentials.
Registration should reject unrecognized configuration rather than rely only on
secret-key-name filtering. Never add this adapter to default/local-zero prices.

A non-local `PricingRevision` requires `local_model_type=None`, an explicit
`usage_reader` (the existing `native_response_usage` handles this adapter's parsed
counters), and an actual `request_guard`. **That guard is not implemented or
registered here.** It must prove that serialized messages plus tool schemas fit
the immutable input-token reservation, output cap fits the reserved ceiling,
and transport/native retries cannot silently enlarge approved usage. The current
1 MiB request byte bound is not a verified tokenizer upper bound. A trusted,
verified tokenizer or separately proven provider input bound is still required.
Native guidance retries also require explicit policy; the transport's zero
network retries alone is not sufficient admission evidence for an entire run.

The existing two-rate ledger computes approved input/output token charges. Go
has model/cache/time-dependent subscription accounting, so those two rates must
not be presented as an exact account bill without further evidence. Missing
usage stays UNKNOWN; using zero pricing merely because a subscription exists is
not evidence of zero consumption or guaranteed absence of balance fallback.
These limits block live model registration even though the isolated transport
and dispatcher-boundary mocks pass.
