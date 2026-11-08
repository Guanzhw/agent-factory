# Runtime

Agno AgentOS 3.1.0 owns the Agent loop, streamed model responses, durable PostgreSQL queue and native cancellation. Factory supplies owner-selected models and native tool functions. There is no separate research scheduler or fixed experiment Workflow.

A conversation turn records its goal, context, model connection and original request. The native run uses that snapshot. Repeating a request reads its existing task; a failed or missing reply is reported as such. This request association supports refresh and correct results without a separate approval or receipt workflow for the user.

File, command, memory, research and collaboration tools are available through the same Agent. Personal MCP and CLI registrations are included directly. The installed Agno Workspace handles file replacement. The existing process helper runs local commands, observes their exit and responds to cancellation. There is no default command deadline or project tool-count quota.

Subassistants use independent native queue tasks with parent links. Waiting continues the original native run when its child has a result. Stop requests apply to the task tree and local owned processes. SSH disconnection alone cannot prove that arbitrary remote background processes have stopped.

A small per-run dispatcher resolves the selected model for the current owner. Agno handles compression and summary generation against known model metadata. Unknown context windows are left unspecified. The remaining Responses codec preserves provider output continuity that the pinned SDK does not yet cover.

The browser receives actual conversation state and model/tool progress. The current SSE endpoint checks for changed snapshots on the server; it is not a cross-replica event bus. Settings and chat share one interface and preserve drafts across navigation.

Provider text and visible reasoning keep their original response identities and order. Adjacent text of the same kind is saved as one segment, flushed at most every 200ms and at segment boundaries or completion. Running turns read these records directly instead of copying every text fragment into the conversation row. The final answer comes from the completed native run's last assistant message; Agno's aggregate run content can also contain earlier messages before tool calls. Older terminal snapshots remain intact.

Chat selects an existing model connection and its verified reasoning effort for the next turn. The native plan pins that choice, including delegated work. Unknown model capabilities expose only the provider default. Auxiliary compression and summary requests do not emit chat content or reasoning.

Removed governance, budget, lease and prepared-handoff services no longer gate Agent execution. Historical rows and user files are preserved. Prior platform and Windows acceptance results apply only to the revisions they exercised; current static checks and actual use are recorded separately.

Native Agno Skills loads instructions and references from bundled research skills, the launch project's `.agents/skills`, and optional `FACTORY_SKILL_PATHS` directories. The pinned loader only discovers immediate resources, so a small subclass lists nested files. Script reads remain native; execution uses the existing research command function, preserving arguments, cwd, full output files, cancellation and original-call replay protection. This replaces the SDK's synchronous 30-second `subprocess.run` path, not the Skills model or parser.

Unknown tool outcomes are returned as observations rather than terminating all subsequent tools. An existing unknown call is not dispatched again. Native turn completion and an individual tool's unknown side effect remain distinct: a completed native turn can permit independent work without resolving the older operation. User Stop and active child execution still use actual runtime status. Research records accept ordinary observations and references; analysis can be standalone or linked to an existing record, with no terminal-record prerequisite.
