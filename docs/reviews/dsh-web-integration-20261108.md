# Local DSH-style chat integration

The chat now uses the local DSH Web reference for its dark layout, centered composer, sidebar, and folded execution details. Agno AgentOS 3.1.0 and the existing PostgreSQL queue still own execution.

The installed `@deepseek-ai/dsh-web-frontend` package is 0.2.2-rc.1, declares MIT, and maps to `apps/web`. `dsh-web-app/lib/index.js` resolves that package’s `dist/index.html`; the host static package serves those built files. Client component packages map to `packages/client/ui-*`. This is version and source metadata verification, not a reproducible-build byte comparison.

## Changed files

| Files | Change |
| --- | --- |
| `web/apps/research/ResearchSessions.tsx` | Sidebar search and collapse, snapshot connection status, compact composer, raw history collapsed by default. |
| `web/apps/research/SessionActivity.tsx` | One latest record per call ID, tool parameters and results, real errors, last-event clock, explicit silence and unknown states. |
| `web/apps/research/ResearchReply.tsx`, `package.json`, `package-lock.json` | Standard remark-gfm 4.0.1 renders Markdown tables and lists. |
| `web/apps/research/chat.css` | DSH-style dark tokens, system fonts, proportions, desktop and narrow layouts, focus and touch targets. |
| `web/apps/research/live/ResearchWorkbench.tsx` | Existing secondary navigation under More. One chat entry and Settings remain. |
| `web/PersonalSSHServers.tsx` | SSH status copy replaces retired training wording and removes the unsupported 15-minute claim. |
| `applications/research/sessions.py` | `_start()` uses the current reserved instruction as the goal; empty-message collaboration continuation keeps the original goal. |
| `platform/agent_factory/native_bridge.py` | Agent submission sends `normalizedGoal` as the native user message instead of a fixed factory-plan instruction. Workflow submission keeps its existing JSON input. |
| `platform/agent_factory/runtime.py` | Native SSH Function pre/post hooks persist paired events, parameters, actual result, and unconfirmed error reason. |
| `applications/research/session_tools.py`, `platform/agent_factory/personal_tool_execution.py` | Existing event payloads include normalized model-provided arguments. Windows directory handles allow native child-file replacement while retaining rename denial and initial reparse rejection. |
| `platform/agent_factory/store.py` | Keeps non-text events when text fragments exceed the recent 1,000-fragment window. |
| `platform/agent_factory/personal_ssh.py` | Uses native `win32api.CloseHandle()` for the token handle, satisfying Windows type checking. |
| `tests/test_chat_journey.py` | Current-message, SSH event, retained-history, and UI-state regressions. Windows assertions use CRLF, ACLs, and a real process handle. |
| `THIRD_PARTY_NOTICES.md`, `docs/DEVELOPMENT_CHECKS.md`, `design-qa.md`, this file | Preserved notices, DSH attribution, checks, visual evidence, and integration contract. |

## Shared-file contract

The existing endpoint remains `GET /api/factory/research/sessions/{id}/events`. It emits owner-authorized SSE `session` snapshots. It never starts a turn. The frontend retains the existing POST and recovery contracts and does not automatically replay work.

Tool events retain these names:

- Research tools: `research_tool_started` and `research_tool_finished`.
- Personal and SSH tools: `tool_started` and `tool_finished`.

Events identify `toolName` and `callId`. New start events include `arguments`; historical records, validation failures, and reconciled finishes may omit them. The frontend takes missing finish arguments from the first start and labels unavailable arguments explicitly. Finished events add `outcome`, optional `output`, `code`, and `message`. `output` may be a list, object, or other native tool result. A command result keeps `exitCode`, `stdout`, `stderr`, and `stopped`. `stopped` describes process custody; it is not the UI cancellation state.

The frontend joins calls by `callId`, retains the first start for time and arguments, and displays the latest finish after reconciliation. Missing end events and unresolved outcomes remain visible after a terminal turn. Elapsed time only measures silence. It does not prove model activity, tool execution, completion, or hidden reasoning.

SSH functions still come from `personal_ssh.functions(owner)` and use Agno Function hooks. Their names, parameters, native execution path, and credential ownership remain unchanged. A native exception without a returned result stays `unknown`; its native error text is shown. Known command exit failures retain their exit code. Remote cancellation cannot establish that arbitrary remote descendants stopped.

Draft [PR #178](https://github.com/Guanzhw/agent-factory/pull/178) shares this branch's base `15e192b24d03aba10c14983ee30461d24e554b95`. Its inspected head is `bf8ad58d1b78fd0df66192f4c1455001beb7ffef`. It adds native Skills and independent continuation after unknown results, with no web or HTTP-route changes.

When integrating, retain the current-message hunk in `sessions._start`, event arguments and Windows directory handling in `session_tools`, SSH hooks in `runtime.selected_tools`, event arguments in `personal_tool_execution`, and native user-message submission in `NativeBridge.submit`. Preserve #178's Skills registration, tool-name reservation, and unknown-result handling. Combine both branches' tests and development-check records. The cloud branch remains separate; combined execution still needs validation.

## Verification

Passed: frozen dependency sync; frontend lint, TypeScript, and production build; Ruff; Pyright; diff whitespace; all seven regressions on disposable PostgreSQL in 63.343 seconds; local Edge screenshots at 1280 × 900 and 390 × 844; sidebar collapse; dark Settings cards; actual tool failure details; live OpenCode Go question, SSH arguments/results, final answer, and refresh recovery.

The live question is exactly `ssh 可用了吗?`. Its supplemental instruction limits the existing host to `hostname`, `id -un`, and `pwd`. The actual model performs discovery and two identical read-only SSH calls. Both return exit 0. Refresh retains one turn and three calls. This is separate from the scripted model and UI snapshot cases.

Resolved Windows failures: the directory guard denied write sharing required by native Workspace atomic replacement. Allowing write sharing while withholding delete sharing makes native creation and existing-file editing work. The suite confirms parent and child file contents, a Chinese-name download larger than 52 KB with exact native-platform bytes, junction escape rejection, and held-ancestor rename failure 32. The fixture now matches the production 35-second transport deadline and checks successful lifespan completion after the thread exits.

The real subscription model also creates, edits and reads a Chinese-named 40-byte file in one turn, using three native file-tool calls. Its final UI shows the expected two lines. Live Edge download acceptance remains incomplete: `downloadMedia` and download-event waiting time out, then Computer Use stops because it cannot reliably establish the browser URL. No further browser actions are taken. This does not invalidate the separate scripted Chromium download result.

Remaining verification limits: Windows TLS/RST 10054 and unclosed-transport warnings remain. The transport deadline expires with zero request tasks, then the queue worker and application lifespan stop successfully. An extra in-place reparse mutation comparison is inconclusive: sandbox attempts fail in the unguarded baseline too, and an elevated attempt is interrupted with execution state uncertain. Rename exclusion and initial reparse rejection are tested; this tool path is not an OS sandbox. Existing selectorless global CSS and bundle-size warnings remain in the successful frontend build.

Unavailable: the requested `iab` surface returns unavailable, so the existing local Edge surface is used. No Library `prepare_materialize` or download helper is exposed in this session. The supplied Library image was not materialized or inspected; actual local DSH and Factory screenshots provide the selected visual reference.

Private evidence lives in `D:/WorkSpace/agent-factory-local/design-evidence/`, including `live-ssh-acceptance.json`, screenshots, and check output. None belongs in the source commit.

## Local preview

The existing HTTPS app is running at `https://127.0.0.1:3100/`. The existing local startup script is `D:/WorkSpace/agent-factory-local/start-service.ps1`. The backend was restarted after loading the request and event changes, retaining the existing PostgreSQL data.

Local branch: `codex/dsh-chat-observability-windows-20261108`. The local commit and [Draft PR materials](dsh-web-draft-pr-20261108.md) preserve this work for integration. No push, remote pull request, merge, publication, or deployment is performed.
