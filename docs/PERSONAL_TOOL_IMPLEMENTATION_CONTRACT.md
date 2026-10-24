# Personal CLI and MCP implementation contract

The current member workflow is documented in [Member tools](MEMBER_TOOLS.md); [connection lifecycle](PERSONAL_TOOL_CONNECTION_LIFECYCLE.md) describes resource custody and original-operation recovery. This contract covers both member-defined resources and existing installed integrations.

## Modules

| Module | Responsibility |
| --- | --- |
| `personal_tool_contract.py` | Descriptor, invocation and fixed-error contracts; standard tool schemas |
| `personal_tools.py` | Owner resource records, MCP discovery, optional credential references, sharing, immutable runtime declarations and native registry restoration |
| `personal_tool_execution.py` | Agno Function wrapping, current actor/resource checks and existing durable effect receipts |
| `personal_cli.py` | Member-configured command execution and specialized installed CLI credential strategies |
| `_personal_cli_process.py` | POSIX process creation, bounded IO, cancellation and process-group stop evidence |
| `personal_mcp.py` | Official SDK discovery and one-call session execution |
| `PersonalToolConnections.tsx` | Member configuration, token saving, discovery, binding, sharing and original-request recovery |

Core/adapters import no research application. Composition provides a default encrypted vault and restores member tools; applications consume the native binding without another execution engine or per-tool permission registry.

## Configuration boundary

`POST /personal-tools/resources` normalizes and validates the member resource once. CLI fields include executable, arguments, working directory, explicit environment, JSON Schema, scalar option mappings, JSON-stdin selection and JSON/text output. An authenticated CLI also declares the credential environment variable. MCP fields include the selected HTTP(S) URL, remote name, native name and discovered schema. Credentials are optional and otherwise name an exact vault reference/revision owned by the resource owner.

The saved body contains immutable configuration metadata and a descriptor snapshot. It never contains vault secret values. Public projections include the native `runtimeBinding` and current availability. Team projections omit credential references/revisions. Sharing records track personal/team visibility separately from immutable configuration identity.

Startup calls `PersonalTools.register(bindings)` after installed registrations. New resources install the same native registration on save. Another worker resolves a missing member adapter by ID through `ensure_registered`; its source is the persisted resource record. Missing IDs fail as unavailable. Record-integrity or malformed configuration failures remain explicit.

Installed integrations can still use `Settings.personal_tool_adapters` and the existing installed-adapter configuration endpoint. They do not gate member resources.

## Invocation contract

`ToolInvocation` carries the requesting actor, original connection/call identity, native RunContext, business arguments and current authorization/credential callbacks. A resource handle separately retains the credential owner. `resolve_credential()` returns a redacted `SecretLease` for the exact scope or `None` for an unauthenticated resource.

The native wrapper reserves the existing durable effect before transport dispatch. Only `new` dispatches; `done` rechecks current access and returns the retained receipt. UNKNOWN stops further model turns without redispatch. Task cancellation, budgets, concurrency reservations, current account state, connection revision, sharing and credential state remain active operational checks.

`ToolInvocationError` contains a fixed code, business outcome and positive local `stopped` evidence. A failed operation with unresolved cleanup retains UNKNOWN capacity; local process or session closure does not establish that a remote effect stopped. Known secret echoes and oversized results never enter retained output.

## CLI

The member adapter starts the member-selected executable once, using argv rather than an implicit shell. It honors the selected working directory and environment, passes JSON stdin by default, maps declared options when selected, and parses JSON or wraps text output. Credential injection is explicit. Independent invocations use independent temporary state, and the adapter leaves the service environment unchanged.

Specialized installed `PersonalCliAdapter` integrations retain their declared credential-delivery/probe behavior. Those probes are specific to that integration and are not prerequisites for arbitrary member commands.

The process helper supports POSIX process groups. Windows-hosted CLI execution is rejected explicitly; Windows browsers can manage a Linux deployment. Timeouts and cancellation settle the owned local process group before reporting positive stop evidence. Temporary credentials remain when stop cannot be confirmed. Debug event loops are rejected because low-level pipe diagnostics can precede echo filtering.

## MCP

Discovery and invocation use official `mcp==2.3.0` `ClientSession` and Streamable HTTP. Endpoints support HTTP/HTTPS, local/private/public hosts, IPv6 and custom ports. HTTPS keeps certificate verification. Each invocation owns its client/session, verifies the selected schema and sends one business call. Input-required replies, schema changes and network failures do not trigger an automatic repeat.

Authorization is owner-scoped for every protocol request and session DELETE. Unauthenticated resources omit the Authorization header. Requests stay on the configured endpoint; redirects, ambient proxy settings and transport retries are disabled. A two-second default DELETE deadline spans authorization, response headers and response body streaming. SDK cleanup and business outcome have separate evidence.

## Acceptance evidence

Focused tests use local processes, synthetic credentials and local MCP servers. They cover configuration persistence, real input/output contracts, concurrent owners, credential echoes, cancellation, schema changes, failed cleanup and original-effect recovery. The PostgreSQL restart test starts an independent worker process before member configuration exists, publishes materials/application through authenticated member APIs, then executes the real command through the native queue. Repeating the request and reopening services retain the task/run and execute the command once.

Retained-handle tests prove that disabled callers, withdrawn sharing and revoked owner credentials prevent another command. Vendor model/service compatibility and externally deployed throughput require separate target evidence. See [development checks](DEVELOPMENT_CHECKS.md#personal-cli-and-mcp-verification) for runnable commands.
