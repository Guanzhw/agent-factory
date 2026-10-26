# Member CLI and MCP tools

Open **我的资源 → 管理工具** (My resources → Manage tools) to connect a tool. Any active member can create a personal resource, bind a team resource, and publish materials or applications that use it. Each resource starts as personal. Its owner can select **Share with team** and later return it to personal visibility.

MCP resources accept HTTP or HTTPS URLs, including localhost, private networks, IPv6 and custom ports. HTTPS verifies the server certificate. Select **Discover MCP tools**, select a returned tool, and save it with a native call name. Discovery reads the server's tool declarations. The selected tool's JSON Schema is checked again before its first business call in each session; a changed schema produces an explicit error.

Leave **Access credential** empty for a service that does not require authentication. For an authenticated service, enter the access token and select **Encrypt and save token**, then select the saved credential. MCP sends that owner's token as a Bearer token. The encrypted vault keeps credentials separate from tool declarations; team members use the owner's credential without seeing its value or reference.

## A CLI command

CLI commands run on the Linux deployment host. Enter an absolute executable path, a JSON argument array, an optional absolute working directory, and any user configuration environment variables. The default input contract sends the call's JSON arguments to stdin. Select JSON or text output to match the command. For a command that accepts credentials through an environment variable, save its token in the vault and enter the variable name.

For example, this local Python command accepts `{"query":"example"}` and returns JSON:

```json
{
  "transport": "cli",
  "toolName": "my_lookup",
  "description": "Return a query with my selected configuration",
  "executable": "/usr/bin/python3",
  "arguments": ["-c", "import json,os,sys; print(json.dumps({'query':json.load(sys.stdin)['query'],'mode':os.environ['LOOKUP_MODE']}))"],
  "workingDirectory": "/srv/team/project",
  "environment": {"LOOKUP_MODE": "project"},
  "inputSchema": {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
    "additionalProperties": false
  },
  "outputFormat": "json",
  "requestId": "my-first-lookup"
}
```

Send this configuration to `POST /api/factory/personal-tools/resources` through the authenticated factory API. The page exposes these same fields. Choose a working directory that exists on the deployment host. Configuration is stored for the resource owner; secret values belong in the vault rather than `environment` or command arguments.

The API also supports `argumentOptions` when a CLI reads flags instead of JSON stdin. For example, `"argumentOptions":{"query":"--query"},"stdinJson":false` turns a scalar `query` input into `--query=value`. Boolean values append their flag when true. `timeoutSeconds` defaults to 30 and `maxOutputBytes` to 65536. The process helper enforces these bounds and terminates its owned local process group on timeout or cancellation.

## A MCP resource through the API

Use `POST /api/factory/personal-tools/discover` with `{"url":"http://localhost:8900/mcp"}`. If authentication is required, include the selected `credentialRef` and `credentialRevision`. The response contains the normalized URL and the discovered tools' names, descriptions and input schemas.

Save one selected tool with `POST /api/factory/personal-tools/resources`:

```json
{
  "transport": "mcp",
  "url": "http://localhost:8900/mcp",
  "remoteToolName": "lookup",
  "toolName": "my_server_lookup",
  "description": "Lookup on my MCP service",
  "inputSchema": {"type":"object","properties":{"query":{"type":"string"}},"required":["query"]},
  "requestId": "save-my-mcp-tool"
}
```

Use the schema actually returned by discovery. Tool calls use the official MCP SDK and a separate authenticated session for each invocation. Session cleanup does not establish that a remote effect stopped; an uncertain result retains its original effect identity.

## Use the resource in an application

Saving through the page also binds a user connection. An API client can bind the returned `registrationRef` with `POST /api/factory/user-connections`, providing a fresh `requestId` and `capabilities:["tool:invoke"]`.

Expand **Component runtime declaration** on the saved tool and copy its `runtimeBinding` into a tool material. Set that material's `content` to the tool's native call name and its `permissions` to `["tool:invoke"]`. For a named application connection, include `"connectionName":"lookup"` in the binding's `config`. Publish the material directly, then include its exact material reference in the application's mode, list the native call name in `toolOrder`, and declare a tool connection named `lookup`. Select the user connection when starting the application.

The returned declaration has this shape; IDs are generated for each saved resource:

```json
{
  "adapterId": "member-tool-<generated-id>",
  "revision": "1",
  "config": {"connectionName": "lookup"}
}
```

Resources persist across service restarts. A worker that has not seen a resource loads its adapter from the saved record when it resolves the material binding. Adding a member tool requires no deployment-side tool registration.

## Shared tools and recovery

The owner controls sharing and revocation. Another member can select **Bind this tool** for a team resource and use it in their own application run. The caller's account, current sharing state and the owner's credential revision are checked before a new operation. Withdrawing sharing, disabling the caller, or revoking the credential prevents a retained handle from dispatching another operation.

When a save, binding or sharing response is lost, use the page's original-request recovery action. It reads the original receipt. API clients use `GET /api/factory/personal-tools/requests/{requestId}` for configuration or sharing and `GET /api/factory/user-connections/requests/{requestId}` for a binding. A repeated application start keeps its task and effect identities. An UNKNOWN external effect must be reconciled before another operation is started.

Back up the database together with `<workspace>/runtime/credential-vault.key`. Keep that workspace when restarting so the existing key can decrypt saved credentials. An explicitly configured organization vault retains its own key-backup procedure.
