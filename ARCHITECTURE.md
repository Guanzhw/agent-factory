# Architecture

Agent Factory provides execution and shared resources for a trusted small team. Its default application is AutoResearch: one conversation-oriented interface where an Agent chooses tools, experiments, and collaborators from the user's goal. The application does not impose a fixed research sequence.

## Application and platform responsibilities

| Layer | Responsibility | Source |
| --- | --- | --- |
| Core | Native execution, identities, resource ownership, bindings, receipts, cancellation, and execution capacity | `platform/agent_factory` |
| Research application | Conversations, research context, experiments, interpretations, and research tools | `applications/research` |
| Adapters | Concrete model, command, MCP, SSH, and remote-service integrations | Registered through core contracts |
| Composition | Application selection and trusted adapter registration | `deployment/agent_factory_server` and frontend composition files |

Core does not import research implementation. Applications use core contracts and declared public application interfaces. The [Python ownership map](scripts/architecture-python.json) and [frontend ownership map](scripts/architecture-web.json) define the checked paths and composition exceptions.

`agent-factory` and `agent-factory-research` both select `agent_factory_server.research:main`. The default browser build uses the research composition. The standalone core factory and package remain available for programmatic assembly and boundary checks. They are not a second product workflow.

## Execution ownership

Agno AgentOS 3.1.0 owns the model and tool loop, durable PostgreSQL queue, native run state, and native cancellation. Factory stores the application records that connect user requests to those runs: plans, owner bindings, tool receipts, resource allocations, and content references.

Research uses that existing execution path. Reusable practices are callable tools, not mandatory stages. An Agent may answer directly, run a local experiment, or delegate useful independent work. The [autonomy decision](docs/plans/agent-autonomy-20261106.md) supersedes the earlier fixed research controller and parallel project/session entry points.

A missing reply does not authorize a second execution. Recovery reads the original request, task, and effect. Native task completion and confirmed process stopping are separate facts. [Runtime design](docs/RUNTIME_DESIGN.md) describes these contracts.

## Team and resource ownership

Members publish and manage their own materials and applications. Administrators manage accounts. Resource owners configure connections and choose personal or team sharing. Another member can use a shared connection without receiving its secret.

The deployment target is one application process with PostgreSQL and a configurable worker pool. The approximate 20-member target is a usage goal, not a measured concurrency guarantee. Remote runtime attachment and remote machine allocation are separate operations. SSH command execution does not imply GPU allocation support.

## Acceptance boundaries

The repository checks three distinct boundaries:

1. The standalone core installs without application source, starts against disposable PostgreSQL, and shuts down.
2. Dependency checks reject forbidden direct and indirect imports across the ownership maps.
3. Application checks exercise selected models, owner isolation, original-request recovery, and actual process stopping.

Synthetic provider tests establish these contracts. They do not prove external identity, real-model quality, target-machine capacity, or GPU behavior. Exact execution results belong in the corresponding PR or dated acceptance record. [Development checks](docs/DEVELOPMENT_CHECKS.md) lists the commands and their scope.

Historical ORX and fixed-workflow records remain available in the [documentation map](docs/DOCUMENTATION_MAP.md). Their commands and acceptance results do not establish current AutoResearch behavior.
