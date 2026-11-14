# Architecture

Agent Factory is a chat application for a trusted small team, built on Agno AgentOS 3.1.0 and PostgreSQL. The browser opens a conversation; models, tools, credentials and SSH connections live in Settings. An Agent chooses useful tools and subassistants from the user's goal.

## Implementation

- `platform/agent_factory` provides identity, personal/shared resource configuration and the thin connection to Agno execution.
- `applications/research` stores conversations, optional project goals, personal preferences, curated research records and team questions.
- `deployment/agent_factory_server` installs the research application in the service.
- `web` provides the single chat and settings interface.

Agno owns model/tool execution, streaming, PostgreSQL queue tickets, cancellation and continuation. A small dispatcher selects the current user's model for a native run; the shared Agent's model is never mutated to another user's credentials. Research and personal tools become native Functions directly.

The conversation is submitted with its goal, context and model connection. It does not first create or publish materials, applications, capability manifests or budget scopes. Subassistants inherit their parent's model and tools and run through the same native queue.

Files use Agno CodingTools. The configured session workspace is a default directory, not a file-access boundary; absolute research paths are supported. Shell execution alone uses the existing cancellable process helper. MCP uses the official SDK with Agno tool discovery. SSH uses system OpenSSH; configured remote Agno agents use AgentOSClient. Optional research records and shared answers do not impose a fixed research sequence.

## Data and maintenance

User/resource associations, actual errors and user-requested stopping remain functional requirements. Removed services do not delete historical database rows, credentials or user files. Older design and verification documents describe their recorded revisions; they are not a description of the current implementation.

The former manual Factory assembly, review, workflow custody, resource lease, budget, deployment-manifest and storage-administration layers are retired. Their duplicate interfaces and dedicated checks are removed. See [Development checks](docs/DEVELOPMENT_CHECKS.md) for the current static commands and actual-use verification scope.
