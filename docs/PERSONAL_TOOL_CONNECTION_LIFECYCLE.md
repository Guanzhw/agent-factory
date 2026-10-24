# Personal CLI and MCP connection lifecycle

Members connect their own tools through **Connections → My tool connections**. The practical setup guide and JSON examples are in [Member tools](MEMBER_TOOLS.md). Installed adapters remain usable, while member CLI/MCP resources require no deployment-side per-tool registration.

## Resource creation and sharing

A member chooses a MCP endpoint and discovers its tools, or supplies a Linux CLI executable, arguments, working directory, environment and input/output contract. MCP supports HTTP and HTTPS with localhost, private networks, IPv6 and custom ports. HTTPS retains certificate validation. Unauthenticated resources omit credential references. Authenticated resources resolve an owner-scoped encrypted vault credential at invocation time.

A saved resource has an immutable registration/revision and a public native runtime declaration. The page binds a user connection with a separate request ID. A tool material uses the returned adapter ID/revision, the native tool name as `content`, and an application connection name in `runtimeBinding.config.connectionName`. The application declares that connection and selects its user connection at submission.

Resources default to personal visibility. Only the owner changes configuration, sharing or revocation. Team members see public tool metadata and can bind a connection owned by themselves; responses omit the resource owner's credential references. Runtime handles retain both the requesting actor and credential owner. Immediately before another operation, the handle checks current membership, sharing, resource state and credential revision.

## Core and adapter responsibilities

| Layer | Responsibility |
| --- | --- |
| Core | Persistent resource records, connections, encrypted credential custody, native Agno Functions and original-effect receipts |
| Application | Exact material references, native tool order, connection requirements and business inputs |
| Member CLI adapter | Configured argv/workdir/environment, JSON stdin or option mapping, declared output format and owned process-group cleanup |
| Installed CLI adapter | Existing specialized credential-delivery and account-probe contract for its installed integration |
| MCP adapter | Official SDK discovery, exact selected tool/schema, per-invocation authentication and session lifecycle |
| Composition | Default local vault, installed integration adapters and loading saved member resources into native execution bindings |

Core startup restores active member adapters from resource records. A worker missing a particular adapter loads it on demand from persistent storage while resolving an execution binding. Materials, applications and workers use the same native registration. A malformed persisted declaration fails explicitly; an executable or working directory that has disappeared is reported unavailable.

`ToolDescriptor` contains the native name/schema, adapter ID/revision, transport, credential scope and timeout/output limits. The configuration stays in the owner resource record; credential values stay in the vault. Standard Draft 2020-12 object schemas are bounded to 32768 bytes; invocation JSON uses the common bounded-data contract. Framework-injected arguments are reserved, and external schema references are not fetched.

## API

All paths below are relative to `/api/factory` and use the existing authenticated browser/CSRF bridge and `X-Factory-Expected-Owner` check.

| Method and path | Behavior |
| --- | --- |
| `GET /personal-tools/descriptors` | Public installed and member resource declarations visible to the member |
| `POST /personal-tools/discover` | Read MCP tools for the selected URL and optional credential revision |
| `POST /personal-tools/resources` | Save a member CLI or selected MCP tool and its immutable runtime binding |
| `POST /personal-tools` | Bind credentials to an existing installed adapter |
| `GET /personal-tools` | Own registrations and team-visible registrations with current status |
| `GET /personal-tools/{registrationRef}` | Inspect a visible registration |
| `POST /personal-tools/{registrationRef}/sharing` | Owner changes personal/team visibility |
| `POST /personal-tools/{registrationRef}/revoke` | Owner revokes a registration |
| `GET /personal-tools/requests/{requestId}` | Read the original configuration, sharing or revocation receipt |
| `POST /user-connections` | Bind the registration as the caller's application connection |

Configuration and binding have separate request IDs and receipts. Recovery reads the original receipt and never interprets a missing response as permission to repeat an external effect. The page retains public request identities across refresh and keeps tokens out of local storage.

## Native invocation and recovery

The native run ID and `fc.call_id` identify one durable effect. Only a new reservation dispatches. A completed reservation returns its original result after current authorization checks. An UNKNOWN effect stops further model turns with Agno `StopAgentRun`; it does not silently create a replacement call. A repeated application start or recovered receipt keeps the original task/run identity.

Business outcome and stop evidence remain separate. A known failed operation with positive local stop evidence may complete its failed receipt. An unresolved cleanup keeps its original UNKNOWN effect and capacity reservation. Ending a local process or closing a MCP session cannot prove a remote mutation stopped.

CLI calls use POSIX process groups on the Linux host. Each member command runs once with the declared arguments, working directory and explicit environment; it gets invocation-owned temporary configuration unless the member explicitly selects other configuration paths. Installed CLI adapters retain their specialized probes. Member commands require no account-probe program. Asyncio debug logging is rejected before subprocess pipes can expose credential input.

MCP calls use the locked official `mcp==2.3.0` SDK's `ClientSession` and Streamable HTTP transport. Each invocation initializes and verifies the selected tool/schema, then sends one `tools/call`. Redirects and automatic transport retries are disabled. Optional Bearer credentials are sent only to the exact configured endpoint. Session DELETE has a two-second total teardown deadline by default; its completion remains separate from business-effect settlement.

Known credential echoes and oversized results are rejected before entering persistent results or model messages. Diagnostic errors use fixed codes. Real local CLI/MCP tests cover these boundaries; compatibility with a particular external vendor still requires a run against that vendor.

## Validation

[Development checks](DEVELOPMENT_CHECKS.md#personal-cli-and-mcp-verification) lists focused commands. `test_member_tool_resources` exercises real local public/authenticated/shared MCP calls and CLI inputs, configuration and native receipt reuse. `test_member_tool_restart_postgres` publishes a member command and application, starts another Python worker before the tool exists, then proves lazy lookup and real queued execution in that process. It also checks retained handles after caller disablement, sharing withdrawal and credential revocation. The model driver is deterministic and local.
