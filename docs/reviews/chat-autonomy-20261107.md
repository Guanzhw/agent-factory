# Chat experience and autonomous execution — 2026-11-07

Implementation baseline: `6a1dd4b7bc3e8134778d1aa25109df9aa38a7ecc`. The user selected the existing Agno architecture, not a Hermes migration. This change combines the UI rebuild, removal of obstructive project restrictions, Codex comparison, and reuse of installed Agno capabilities.

The reference is the open-source Codex client at [`0ed34eb9ceddc759e283f0d657be9339afc6b25a`](https://github.com/openai/codex/tree/0ed34eb9ceddc759e283f0d657be9339afc6b25a), not a claim about every hosted Codex deployment. Agno remains pinned to **3.1.0**. Defaults only transfer where units and scope match.

## Product behavior

The previous research route returned a standalone `ResearchWorkbench` before `Workspace` rendered its shell. Model configuration instead used the core `.factory-shell`. This caused the visible change in navigation, typography, spacing and background. The research composition now wraps chat, settings, models and retained advanced tools in one shell.

A new conversation needs a message and an available model. A title is derived when omitted; extra instructions and project references are optional. Budget and authorization forms are not prerequisites. Enter sends; Shift+Enter inserts a newline. Drafts survive settings navigation and refresh. The sidebar retains conversations; account management appears only to account managers.

Execution shows actual model text fragments, tool starts/results, exit codes, file paths and children. Earlier tool actions can be expanded. Partial model text is not presented as a final answer. A lost acknowledgement reopens the read-only event subscription; it does not submit the work again. Stop remains pending until persisted execution evidence confirms it. The UI follows new output only while the reader remains near the bottom.

Design references: [OpenCode Web](https://docs.opencode.ai/docs/web/), [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness), the user's ChatGPT interaction reference and supplied Factory screenshots. Reference documentation is design research, not a claim that these external products were fully tested in this environment.

## Constraint disposition

The rows follow the original audit's autonomous-session inventory. See the linked implementation and tests for the exact contract; historical values remain readable where needed for old records.

| Original restriction | Implementation and effect | Reference / distinction |
| --- | --- | --- |
| Shared tool count 32, schema 128 | Remove task/ancestor count rejection and schema ceiling; no forced stop at these counts. | Codex [turn loop](https://github.com/openai/codex/blob/0ed34eb9ceddc759e283f0d657be9339afc6b25a/codex-rs/core/src/session/turn.rs#L529); Agno `tool_call_limit=None`. Optional Codex rollout-token policies are separate. |
| Command 120 seconds / maximum 600 | No implicit command deadline; user stop still stops owned processes. | Codex interactive yield is 10 seconds, not process death. Agno native command children yield a durable handle and release the parent worker through native wait; continued reads use the original process. |
| Native task/model total 300 seconds | Agno queue timeout defaults to `None`; model transport uses a 300-second **read-idle** timeout. | Codex [provider idle timeout](https://github.com/openai/codex/blob/0ed34eb9ceddc759e283f0d657be9339afc6b25a/codex-rs/model-provider-info/src/lib.rs#L73). |
| Hidden child depth 2 | Remove entry budget and runtime depth rejection, including database depth ceiling. | Codex V1 depth 1; V2 ignores depth. No universal hosted default is asserted. |
| Hidden cumulative descendants 4 | Remove lifetime descendant rejection. | V1 6 open children; V2 4 total concurrent threads including root. Neither is cumulative work count. Agno's process-wide worker pool is not a per-root Codex slot. |
| Automatic continuation 8 | Remove count rejection, including old saved defaults. | No matching fixed-eight continuation ceiling in the inspected Codex loop. User stop still prevents continuation. |
| Per-user 2 / global 12 active tasks | Remove task-admission count rejection. | No verified equivalent hosted service capacity value; do not invent one. |
| Workers 2 / queue depth 20 | Retain configured Agno worker scheduling; use native unbounded queue setting `0`. | Deployment workers are actual service concurrency, not Agent ability budgets. |
| Whole tool JSON 64 KiB | Remove size-triggered failure; command/CLI/MCP previews retain complete results/artifacts. | Codex returns 10,000-token exec previews, with approximately four UTF-8 bytes/token. Research commands also retain at most 1 MiB in memory while streaming complete output to files; file reads use seek-based previews. Personal CLI/MCP full receipt construction remains a separate adapter scope. |
| Model default 4096 output tokens | Omit the parameter unless explicitly configured. | Codex Responses request omits a default `max_output_tokens`; provider capacity remains real. |
| Model HTTP 1 MiB | Remove project request/response cap; stream provider data. | Codex HTTP response-body limit defaults to `None`. |
| Goal/boundary/message 2000 characters; title 120 | Remove per-field caps. Validate goal plus extra instructions at the same-submission scope, and later messages, against 1,048,576 Unicode characters. Remove the unrelated title maximum. | Codex [`MAX_USER_INPUT_TEXT_CHARS`](https://github.com/openai/codex/blob/0ed34eb9ceddc759e283f0d657be9339afc6b25a/codex-rs/protocol/src/user_input.rs#L10). |
| Context 12000 / summary 3000 / prompt 2500 characters | Remove character ceilings. Use known model context in tokens and the configured threshold or 90% window; unknown windows stay unknown. Reuse Agno summary/compression capabilities. | Codex [model window policy](https://github.com/openai/codex/blob/0ed34eb9ceddc759e283f0d657be9339afc6b25a/codex-rs/protocol/src/openai_models.rs#L568). |
| `add_history_to_context=False` | Keep one projected history source, avoiding duplicate native history. Historical receipts stay in the database. | Agno's default is also false; enabling it alone does not implement correct context management. |
| Explicit memory CRUD, pages of 10 | Retain useful existing memory and continuation. Do not equate pagination with a total memory quota or claim semantic retrieval. | Codex memories feature is optional and default-off in the inspected code; deleting useful memory would not improve autonomy. |
| Edit old/new 12000 characters/bytes | Reuse Agno Workspace exact edit/write; remove project size cap and separate parent-directory creation step. | [Native tool analysis](20261107-research-tools.md). |
| Read full file then 64 KiB rejection | Remove whole-result failure; preserve actual file content. | Codex shell can use ordinary ranged readers; no unverifiable “2000-line default” is asserted. |
| Search 200 entries / 30 matches / depth 8 / 200-character lines | Remove incomplete fixed traversal and line truncation. | Native Agno search has additional defaults that would reintroduce this problem; do not silently substitute them. |
| Relative paths only / 500 characters / blanket link rejection | Path syntax and actual user/session association are separate. Session-internal absolute paths, `..`, links and long paths are accepted; other users’ session roots remain distinct. | Absolute syntax does not imply permission to mix another user's files. |
| Command argv 32 / each 2000 / executable basename only | Remove argument ceilings and basename-only restriction. Preserve precise execution results. | Codex shell/exec does not expose these schema caps. Shell syntax and argv interfaces are not identical. |
| Missing workspace silently removes tools; commands default-off | Default deployment creates a research workspace and enables commands; explicit deployment overrides remain visible. | Codex enables shell/unified exec/TTY in the inspected feature defaults. |
| Same-run lock and `parallel_tool_calls=False` | Permit independent tool calls to overlap; deduplicate the same call identity and protect actual conflicting edits. Remove forced model parallel-disable. | Codex schedules parallel-capable tools concurrently; Agno executes the native tool loop. |
| Shared parent/child working directory | Retain intentional shared workspace. | Codex child environment inheritance also shares files; separate worktrees are not compulsory. |
| Personal CLI/MCP absent from default sessions | Assemble currently available personal/shared registrations through existing bindings; refresh configuration for new turns while retaining old task pins. | Native execution and existing adapters are reused; registration alone is not acceptance. |

## Other user-facing restrictions

Offline team-answer settings now describe their actual purpose. Required answer counts, tool counts, expiry and association recipient counts are removed through the backend, not merely hidden. Evidence/answer truncation is removed. An already enabled old QA configuration upgrades through existing preparation/publication on a new question; old requests retain their original receipts. Explicitly disabled service stays disabled.

Model settings expose optional context-window and compaction-threshold metadata in tokens, preserving it through saved drafts, credential rotation and request recovery. Unknown model capacity is not guessed.

## Implementation map

- Default startup and native tool assembly: `deployment/agent_factory_server/research.py`, `applications/research/session_setup.py`, `session_personal_tools.py`.
- Input, per-turn configuration and context: `applications/research/sessions.py`, `session_context.py`, `session_routes.py`; `platform/agent_factory/input_schema.py`.
- File tools and yielding commands: `applications/research/session_tools.py`, `session_commands.py`, `session_subagents.py`; `platform/agent_factory/_personal_cli_process.py`, `tool_output.py`.
- Delegation and lifecycle: `platform/agent_factory/delegation.py`, `lifecycle_observer.py`, `store.py`, `local_budget_scopes.py`.
- Model streaming and metadata: `platform/agent_factory/byok_model.py`, `model_stream.py`, `model_transport.py`, `owner_runtime_broker.py`, `personal_models.py`.
- Chat and settings: `web/research-composition.tsx`, `web/composition.tsx`, `web/apps/research/ResearchSessions.tsx`, `SessionActivity.tsx`, `chat.css`, `web/ModelSettings.tsx`.

## Verification record

- Real PostgreSQL, native Agno queue and actual files with a scripted model: 129 file-tool calls completed in one turn; a later turn compacted approximately 400,000 characters of history through Agno summary management, retained the original answer and completed. Model token counts use the SDK estimate, not provider billing measurements.
- Native command scenarios include output streaming, cancellation, two parents occupying both workers and yielding to command children, and a parent finishing its native run while its child still runs. The public session must not become idle prematurely.
- Live external model `deepseek-v4.1-flash` completed a new repository-analysis task in 276.606 seconds: default deployment tool assembly, 51,844-byte source read, actual command copy and SHA256/byte verification, 15,130-byte Markdown report and final answer, 336 streamed content events. Internal identity was synthetic; this run is not proof of external SSO.
- A real 601-second command completed through the native command child, original handle reads and native wait (test elapsed 626.117 seconds). Earlier failed attempts remain distinct; the earlier synchronous 601-second probe is not evidence for the new yielding implementation.
- Standalone core wheel was built and installed into an empty environment, started with disposable PostgreSQL, and shut down cleanly. This check does not make a model request.


Final validation, independent review, CI commit, and screenshot acceptance are recorded when the implementation stabilizes. In-progress checks are not whole-product acceptance. Real HTTP/PostgreSQL/browser checks with a scripted provider and a live external-model run are separate evidence categories.

Windows execution, remote GPU allocation and sustained team capacity require their own target environments. No WSP experiment or production deployment is part of this change.
