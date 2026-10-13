# Personal CLI and MCP implementation contract

Base: `3ef542ba0411e70d2d9de25d10124bb6efcebcfe`. This is the implementation contract for PR #88.

## Ownership

| Owner | Files |
| --- | --- |
| A / integration | `platform/agent_factory/personal_tool_contract.py`, `personal_tools.py`, connections/config/main integration, public API, effect wrapper, dependency manifests/lock, architecture/CI maps and PR documentation |
| B / CLI | `platform/agent_factory/personal_cli.py`, `platform/tests/test_personal_cli.py`, CLI-only synthetic fixtures |
| C / MCP | `platform/agent_factory/personal_mcp.py`, `platform/tests/test_personal_mcp.py`, MCP-only synthetic fixtures |
| A frontend agent | `web/PersonalToolConnections.tsx`, `web/personalToolConnectionApi.ts`, associated tests; insertion in ConnectionsPanel and ResourceCenter |

B/C import the dataclasses and Protocol from `agent_factory.personal_tool_contract`. Each adapter exposes `descriptor: ToolDescriptor` and `async invoke(ToolInvocation) -> JSON`. Constructors accept trusted static process/server configuration and injectable transports for tests. They must not edit shared manifests or registration files; send dependency needs to A. No application/research imports.

## Static assembly and credentials

The operator supplies `Settings.personal_tool_adapters`, a tuple of adapter instances. Core registers each exact descriptor with existing `ExecutionBindings.register(kind='tool', connection_kind='tool')`. Application materials name that adapter/revision/toolName and `config.connectionName`; existing `connectionRequirements` and owner connection selection remain unchanged. No dynamic discovery or plugin installation.

Descriptors contain stable adapter ID/revision, tool name/schema, `cli` or `mcp`, exact credential purpose (`credential_provider_id`) and target (`credential_destination`), capabilities and bounded timeout/output. The existing vault must explicitly register the purpose/target policy. Adapter executable/server details are trusted constructor configuration, never member-supplied argv or endpoints.

Core provides authenticated `/api/factory/personal-tools` list/configure/revoke/request-recovery and `/api/factory/personal-tools/descriptors`. Configure accepts `{adapterId, credentialRef, credentialRevision, requestId}` and yields an owner-scoped registration. The existing connection bind API produces the reusable application connection; UI chains this once with separately recoverable request IDs. Secret values enter only the existing vault API and never descriptor, material, plan, effect, command fingerprint or connection JSON.

## Invocation and lifecycle

`ToolInvocation` contains authenticated owner, connection ref/revision, original durable call ID, arguments, native RunContext, `check_authorized()` and `resolve_credential()`. Core reserves the existing effect before dispatch and owns receipts. Adapters check authorization immediately before IO and during execution; resolve returns the existing redacted `SecretLease` after repeating the complete owner/reference/revision/purpose/target check. Adapters must not infer identity from arguments.

Initial authentication lifecycle is one invocation/session, always closed in `finally`; shared immutable schemas are safe. No ambient credentials, fallback to server/global account, automatic retry/redispatch, or auth pooling across owners. CLI owns subprocess/stdin/stdout/file/HOME strategy and positive termination evidence. MCP owns async client/session transport and protocol cleanup. Transport close alone cannot establish remote operation termination.

Return bounded JSON with known credential echoes rejected. Throw `ToolInvocationError` containing only a fixed code: `outcome='failed'` only if execution failure is known, `cancelled` only with `stopped=True`, and `unknown` after ambiguous dispatch. Generic unexpected failures are UNKNOWN. Cancellation/revocation never triggers a replacement operation.

Validation uses synthetic credentials with a real local CLI process and local MCP test server, two-owner concurrency, rotation/revocation, missing credentials without fallback, leak rejection, cancellation and original-effect recovery. No AutoResearch task or real model call. Vendor compatibility is not established by these fixtures.
