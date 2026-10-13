# Personal CLI and MCP implementation contract

Base: `3ef542ba0411e70d2d9de25d10124bb6efcebcfe`. This is the implementation contract for PR #88.

## Ownership

| Owner | Files |
| --- | --- |
| A / integration | `platform/agent_factory/personal_tool_contract.py`, `personal_tool_execution.py`, `personal_tools.py`, connections/config/main integration, public API, dependency manifests/lock, architecture/CI maps, assembly/native PostgreSQL/browser regressions and PR documentation |
| B / CLI | `platform/agent_factory/personal_cli.py`, `_personal_cli_process.py`, `platform/tests/test_personal_cli.py`, `test_personal_cli_process.py`, CLI-only synthetic fixtures |
| C / MCP | `platform/agent_factory/personal_mcp.py`, `platform/tests/test_personal_mcp.py`, MCP-only synthetic fixtures |
| A frontend agent | `web/PersonalToolConnections.tsx`, `web/personalToolConnectionApi.ts`, associated tests; insertion in ConnectionsPanel and ResourceCenter |

B/C import the dataclasses and Protocol from `agent_factory.personal_tool_contract`. Each adapter exposes `descriptor: ToolDescriptor` and `async invoke(ToolInvocation) -> JSON`. Constructors accept trusted static process/server configuration and injectable transports for tests. They must not edit shared manifests or registration files; send dependency needs to A. No application/research imports.

## Static assembly and credentials

The operator supplies `Settings.personal_tool_adapters`, a tuple of adapter instances. Core registers each exact descriptor with existing `ExecutionBindings.register(kind='tool', connection_kind='tool')`. Application materials name that adapter/revision/toolName and `config.connectionName`; existing `connectionRequirements` and owner connection selection remain unchanged. No dynamic discovery or plugin installation.

Descriptors contain stable adapter ID/revision, tool name/schema, `cli` or `mcp`, exact credential purpose (`credential_provider_id`) and target (`credential_destination`), capabilities and bounded timeout/output. The existing vault must explicitly register the purpose/target policy. Adapter executable/server details are trusted constructor configuration, never member-supplied argv or endpoints.

Tool schemas use standard Draft 2020-12 JSON Schema, independently of the smaller application-form vocabulary. The root is an object; the normalized schema is bounded to 32,768 bytes and arguments to 64 KiB, with the shared JSON depth/node/container/string bounds. `fc`, `run_context` and `_agno_run_context` are reserved declaration/input names. Validation uses a registry without external retrieval: it never fetches a remote `$ref`. Descriptors/schema are copied and fingerprinted; changed declarations cannot reuse an existing connection or native wrapper silently.

Settings generates existing adapter/policy registrations and accepts the existing dictionary policy form. Reconstructing core Settings as ResearchSettings reuses the exact generated registration without duplicating it; conflicting adapter instances or policy declarations are rejected. Research composition inherits the generic connection guards rather than providing a separate personal-tool execution path.

Core provides authenticated `/api/factory/personal-tools` list/configure/revoke/request-recovery and `/api/factory/personal-tools/descriptors`. Configure accepts `{adapterId, credentialRef, credentialRevision, requestId}` and yields an owner-scoped registration. The existing connection bind API produces the reusable application connection; UI chains this once with separately recoverable request IDs. Secret values enter only the existing vault API and never descriptor, material, plan, effect, command fingerprint or connection JSON.

## Invocation and lifecycle

`ToolInvocation` contains authenticated owner, connection ref/revision, original durable call ID, arguments, native RunContext, `check_authorized()` and `resolve_credential()`. Core reserves the existing effect before dispatch and owns receipts. Adapters check authorization immediately before IO and during execution; resolve returns the existing redacted `SecretLease` after repeating the complete owner/reference/revision/purpose/target check. Adapters must not infer identity from arguments.

Initial authentication lifecycle is one invocation/session, with invocation-owned teardown in `finally`; shared schemas and executables carry no mutable owner authentication. No ambient credentials, fallback to server/global account, automatic redispatch, or auth pooling across owners. CLI owns subprocess/stdin/stdout/file/HOME strategy and local process-group evidence. MCP owns async client/session transport and protocol cleanup. Neither transport close nor local process termination establishes remote operation termination. Unconfirmed local stop retains the CLI private directory; cleanup is not an unconditional guarantee.

Return bounded JSON with known credential echoes rejected. Throw `ToolInvocationError` containing only a fixed code. Business outcome and local `stopped` evidence are independent: a failed read-only probe may establish that business was never dispatched while reporting `failed, stopped=False`; this must not delete the private directory or imply cancellation/complete cleanup. `cancelled` requires positive stop evidence for the affected operation; an ambiguous dispatched business operation remains `unknown`, including a CLI whose local process group has since stopped.

Core reserves by native run ID and original `fc.call_id`. Only `new` dispatches; `done` rechecks authority before returning the retained receipt. UNKNOWN raises native Agno `StopAgentRun` so a later model turn cannot replace the uncertain call with a new call ID. This does not undo other calls already dispatched concurrently in the same batch. Native queue completion/cancellation alone cannot settle the original UNKNOWN effect. No remote exactly-once guarantee is claimed.

For a known failure, `stopped=True` allows the failed receipt to complete the effect. `stopped=False` records `{outcome: "failed", stopped: false}` while keeping the effect UNKNOWN and retaining capacity; native `StopAgentRun('PERSONAL_TOOL_FAILED_CLEANUP_UNCONFIRMED')` prevents continuation. Restart preserves both the failure result and unresolved custody. A later task is still rejected when the retained reservation exhausts its capacity limit.

## CLI adapter constraints

`PersonalCliAdapter` uses the owned POSIX process helper; real process acceptance runs on Linux. Windows-hosted CLI execution is unsupported. Browser configuration on Windows is independent of the server's process platform.

A successful invocation runs three sequential processes under one execution deadline: an absent-credential negative probe, a supplied-credential identity/source probe, then the business command. Trusted registration must make both probes read-only and supply expected unauthenticated exit codes plus an identity/source verifier. A rejected probe never starts business. Executable contents and current authority are checked before each spawn. Only registered scalar business flags are mapped into argv; no shell or member-selected executable/authentication flags are accepted.

Credential delivery explicitly selects stdin, a file, an environment variable or a private HOME file. Each invocation gets separate HOME/config/cache/temp state and an explicit child environment, without mutating the service environment. There is no persistent refresh/cache mode. Asyncio debug mode is rejected before secret/process work and rechecked during execution because pipe debug records can expose payloads before filtering; the adapter does not change the shared event loop or global logging settings. These same-UID processes are not hostile-code or network isolation.

Probe failures and business dispatch retain separate state. A business command's nonzero exit, timeout or interrupted acknowledgement remains UNKNOWN even after local termination. Private credentials are deleted only after local stop is established; deletion failures are sanitized errors. Local stop evidence does not cover descendants that deliberately leave the process group.

## MCP adapter constraints

`MCPToolAdapter` uses official `mcp==2.3.0` `ClientSession` and Streamable HTTP with its SDK-compatible HTTP client. It does not depend on FastMCP, start stdio servers, or use legacy SSE transport. Each invocation initializes and verifies the exact registered tool/schema before one `tools/call`; human-readable schema annotations may differ, but validation keywords, property names and typed literal values remain pinned. Input-required replies do not trigger automatic follow-up calls.

HTTPS is required by default. `allow_loopback_http=True` is an explicit fixture option restricted to numeric loopback addresses. Requests are pinned to the exact endpoint, with redirects, ambient proxy configuration and transport retries disabled. Fresh owner-scoped Bearer authorization applies to protocol requests and session DELETE; credentials are not stored on the shared adapter.

`teardown_timeout_seconds` defaults to two seconds and bounds session DELETE across credential/authority checks, response headers and all response body chunks. Repeated cancellation waits for the invocation-owned SDK cleanup path. This bounds the DELETE exchange, not arbitrary injected transport code or the lifetime of a blocking synchronous authorization thread, and does not prove remote operation cancellation or session deletion. SDK/session resources and the business effect remain separate evidence.

Before `tools/call` dispatch, a failed invocation may attest `stopped=True` once its local tasks, authorization callbacks, SDK contexts and transport have finished. Session DELETE is best effort: an idle remote session, including a server that rejects DELETE, does not establish a running business call and must not alone retain call capacity. Incomplete local cleanup still retains UNKNOWN capacity. After business dispatch, failure or transport closure alone does not prove remote stop and cannot establish `stopped=True`.

## Validation scope

Validation uses synthetic credentials with real local CLI processes and a local MCP protocol server, two-owner concurrency, rotation/revocation, missing credentials without fallback, leak rejection, cancellation and original-effect recovery. Shared adapter integration tests call these real local adapters through `FunctionCall.aexecute()` and the wrapper, using an in-memory effect fixture to prove DONE replay does not redispatch. Separate real PostgreSQL/Agno tests exercise declared applications, inert synthetic tools and the local MCP server, using a deterministic model fixture. They check repeated native calls, restart receipt recovery, pre-dispatch failure capacity release, UNKNOWN native stop, retained capacity after failed/unconfirmed local cleanup and denial of the next call after revocation. Chromium checks the built resource/connection UI with all API responses intercepted, including lost acknowledgements, revoked recovery, owner changes and recovery from unsent steps or explicit binding refusals. Current browser evidence uses desktop widths; narrow viewport cases remain optional. No AutoResearch task or real model call is required. See [development checks](DEVELOPMENT_CHECKS.md#personal-cli-and-mcp-verification); external-vendor compatibility remains unverified by these fixtures.
