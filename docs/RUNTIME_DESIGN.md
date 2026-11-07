# Runtime design

This reference describes the current Agno integration. [Architecture](../ARCHITECTURE.md) defines package responsibilities. Historical experiments and retired ORX workflows are indexed separately in the [documentation map](DOCUMENTATION_MAP.md).

## State ownership

| Owner | State |
| --- | --- |
| Agno AgentOS | Native runs, sessions, queue claims, model and tool execution, and native cancellation |
| Factory core | Immutable plans, owner and resource bindings, admission records, effect receipts, and resource custody |
| Research application | User conversations, goals, research context, experiments, interpretations, and shared research content |

The native queue executes registered Factory operations. Factory application state derives from native state and recorded effects. A second application scheduler does not replace the queue.

## Requests and receipts

A request records its identity before dispatch. Repeating that identity reads the existing receipt. A missing reply or an uncertain effect remains `UNKNOWN`; it does not authorize replay or release occupied capacity.

Plans retain their selected material and connection revisions. Later catalog changes do not rewrite a running plan. Current ownership and resource availability still apply to new calls. [Control commands](CONTROL_COMMANDS.md) and [event replay](EVENT_REPLAY.md) describe the persisted interfaces.

## Autonomous research

`ResearchSessions` submits work through the existing native Agent. The Agent selects tool order and whether an experiment or delegation is useful. Research context, experiment records, and interpretation tools are available without requiring a fixed sequence.

Local research tools read, search, create, and edit files in their workspace. The default deployment supplies a research workspace and command tools; an explicit deployment override can select another workspace or disable host commands. The tools return exit codes, output, and file hashes. A command's nonzero exit is an observation the Agent can use, not an automatic failure of the entire conversation.

[Personal research sessions](PERSONAL_RESEARCH_SESSIONS.md) describes the user journey. The [autonomy decision](plans/agent-autonomy-20261106.md) records why the fixed controller and second product entry were removed.

## Delegation and execution capacity

Each child has its own native task and a persisted parent/root relationship. Project depth, cumulative descendant, and tool-count ceilings no longer stop the subtree. Historical plan budget fields remain readable; new autonomous work does not inherit their former default ceilings. Agno workers schedule actual execution capacity.

Original call accounting remains available for recovery; it no longer enforces a lifetime tool quota. The native Agent does not have a duplicate per-run tool-call limit. Native workflow support remains available for applications that choose it. It is not a mandatory research framework. [Delegation](DELEGATION.md) describes the shared interfaces.

## Credentials and shared resources

Connections belong to members. Owners configure them and choose personal or team visibility. Shared use resolves credentials inside the service and retains the caller's task identity. Credentials are not catalog material or prompt content.

The normal owner-model path supports the protocols in [model compatibility](MODEL_PROTOCOLS.md). [Owner BYOK](owner-byok-api.md) distinguishes provider billing from Factory accounting. [Resource sharing](RESOURCE_SHARING.md) defines visibility and revocation.

## Stopping and recovery

Cancellation records intent and requests native cancellation. The lifecycle observer inspects the original task tree and existing effects. It does not start replacement work. Capacity is released when native state and effect/process evidence establish that the owned work stopped.

Windows commands use owned Job Objects. POSIX commands use owned process groups. Directory separation and process cleanup do not establish hostile-code isolation. [Lifecycle observation](LIFECYCLE.md), [process leases](PROCESS_LEASE_RUNTIME.md), and [security assumptions](SECURITY.md) describe the separate guarantees.

HTTP shutdown has two stages: Uvicorn drains network work, then application lifespan cleanup stops workers and releases services. Official launchers give each stage a 35-second budget. These are sequential budgets, not a single 35-second deadline. See [shutdown behavior](SHUTDOWN.md), including the Windows TCP/TLS reset limitation.

## Remote execution and scheduling

A runtime attachment identifies an existing receiver. Allocation chooses an execution environment. Neither operation implies cloud provisioning. The SSH helper reports `gpuAllocation=false` and `scheduler=false`; its provider rejects `gpuBinding`. Remote GPU execution therefore needs more than model or host credentials.

Agno's schedule poller supplies the clock and queue integration. Factory validates occurrence admission and retains original receipts. Current deployment coordination assumes one application process. [Remote resources](REMOTE_RESOURCES.md) and [scheduling](SCHEDULING.md) define these interfaces.

## Evidence limits

A native Windows CPU research acceptance used a real model, produced executable code and reproducible result files, and confirmed original-task stop. With the transport shutdown deadline configured, the application completed lifespan cleanup and exited after the observed TCP/TLS reset. This does not certify every research task or normal socket cleanup. Registered artifact downloads, persistent user login on the target installation, remote GPU allocation, and sustained team capacity require their own acceptance.

Earlier Linux, ORX, fixed-program, and synthetic-user results remain evidence for their recorded revisions. They are not current deployment certification.

The [2026-11-07 review](reviews/chat-autonomy-20261107.md) records the Codex comparison, native Agno reuse, and validation boundaries for chat, streaming, context and tool changes.
