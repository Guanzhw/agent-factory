# Development checks

## Shared-source continuation validation on 2026-11-08

The baseline reproduces a completed chat losing its Start action after a source is made private. Two PostgreSQL/native-queue/Chromium journeys pass after the fix (35.117 seconds): preserved chat history, a fresh provider HTTP payload without the revoked source, derived reply, old correction or saved summary, an independent file write, duplicate submission/refresh, and revocation during a run followed by a new successful turn. The old correction and summary are synthetic persisted fixtures; summary generation itself is not exercised by these two journeys.

Independent review found an auxiliary-model gap: native tool compression could send a withdrawn source before the primary model hook ran. A further native CompressionManager journey now explicitly selects its low-threshold model and revokes the source at compression entry. Removing only the auxiliary hook reproduces extra provider requests; the hooked path makes only the original pre-revocation request. All three source journeys pass together in 48.178 seconds. Auxiliary requests share the source/Stop check without recursively preparing another summary.

An additional owner-access journey removes duplicated `team`/`research` checks after `content.read`: an owner's published `notes` record remains readable after becoming private, the original chat context survives, and another member cannot read either that record or a team-visible derivative. The four source journeys pass together in 53.042 seconds; the final owner case additionally verifies browser source display and derivative access in 15.097 seconds. The pinned-effort fixture now distinguishes primary and auxiliary hooks without recursively creating another auxiliary model. Its six cases and all 36 non-browser regressions pass (7.170 seconds for the latter).

Two focused cases cover automatic collaboration reservation using the same clean context, unavailable adopted replies, later summary/checkpoint projection, and temporary source-service errors. Four existing session recovery/Stop cases also pass. Frontend checks, Ruff and Pyright pass; Linux still reports six unavailable Windows-import warnings. The model is a local scripted HTTP fixture. No paid model, remote SSH, external MCP or complete peer-assistant exchange was used for this change.

## Thinking and diagnostic validation on 2026-11-09

The scoped DeepSeek thinking request, nullable stream role and separate diagnostic entry pass all 41 minimal cases on Windows in 171.505 seconds. Frontend checks, Ruff, full-worktree Pyright and whitespace checks pass. Real-provider observations include thinking/content, tool exit 0/7, native Stop and refresh; synthetic cases separately cover unknown/recovered receipts and reading position. Historical role failures and existing platform warnings remain distinguished from the passing final checks. See [the acceptance record](reviews/deepseek-thinking-diagnostics-20261109.md).

## DSH interaction validation on 2026-11-08

The ordered chat correction passes all 39 minimal cases on Windows with isolated PostgreSQL 17 in 153.583 seconds. Frontend lint/types/build, Python Ruff, full-worktree Pyright and whitespace checks pass. The build retains baseline empty-selector and bundle-size warnings. The existing Python environment is reused without running `uv sync` against the live service.

Native HTTP fixtures cover interleaved thinking/content, three disclosure levels, stable tool rows, model/effort request serialization, unknown outcomes, Stop, refresh, long conversations and stale file previews. Three real-process cases cover long Windows output paths, exit 7, Stop and output-preparation rejection. Independent review also checks long-path file listing/download bytes and retained directory protection.

The local DSH page and installed frontend are inspected directly. Actual DeepSeek high/low requests, visible reasoning, file creation/read, command exit 0/7, native Stop of a live PID and read-only recovery are separately verified. After the user confirms Save in Edge, the final 2,240-byte file matches the workspace and API download byte-for-byte and by SHA-256, with no temporary download remaining. Luna/low returns HTTP 403. Computer Use stops before final-patch UI Stop; that remains distinct from the passing scripted browser and real API evidence. See [the interaction acceptance record](reviews/dsh-chat-interaction-20261108.md).

The old test suite was deleted at the user's request on 2026-11-07. The user subsequently requested minimal feature-based regression coverage using Ponytail. The new suite covers a small set of browser journeys and focused review regressions; it does not restore the old tests or their implementation constraints.

## Run

```sh
uv sync --frozen
npm ci --ignore-scripts
npm run check
uv run ruff check platform deployment applications tests
uv run pyright
uv run playwright install --with-deps chromium
FACTORY_TEST_DATABASE_URL=postgresql+psycopg://user:password@127.0.0.1:5432/postgres \
  uv run python -m unittest discover -s tests -v
```

Use a disposable PostgreSQL instance with permission to create databases. Each suite run creates a random `factory_regression_*` database, runs the actual application and queue, and drops only that database afterwards. It uses temporary files, local TLS, synthetic accounts and a local scripted Chat Completions SSE server. No paid model or real SSH host is contacted. Chromium is the only browser dependency. A missing database URL or browser fails visibly rather than silently skipping the suite.

## Coverage

Two focused cases exercise SSH revocation through the real database/API and native Agno compression through a local model endpoint. SSH process spawning is intercepted only to inspect temporary-key permissions and cleanup; this is not a remote SSH execution test. The compression case checks Chat Completions and Responses request serialization with compression enabled and disabled. A third case verifies that the low-level workspace opener accepts only a leaf name, rejecting traversal and absolute paths without silently rewriting them.

- Ordinary login opens chat; model configuration through Settings selects the model used by the Agent.
- A chat draft survives a settings visit. A streamed response and native tool calls travel through the actual model HTTP adapter and Agno queue.
- A configured CLI's exit 7 preserves stdout/stderr and the Agent continues with another call.
- The Agent receives the configured SSH server reference from discovery without user input.
- The exact question `ssh 可用了吗?` and its follow-up remain native user messages. SSH discovery emits paired events with arguments and results. Tool history survives more than 1,000 text fragments.
- A native SSH result with exit 255 and `stopped=False` retains its output and remains unknown in saved events and the UI.
- SSH boundary coverage also includes empty/missing argv, preparation failure and confirmed spawn rejection as failed; dispatched loss, cancellation and execution cleanup failure remain unknown. The native model/queue/browser journey checks actual saved outcomes and whether process spawning was attempted.
- A separate UI snapshot case covers missing events, transport EOF and reconnection, terminal unknown results, later reconciliation, one row per call ID, Markdown tables, and narrow screens. These snapshots are synthetic and do not prove provider or SSH connectivity.
- Native file creation and replacement produce a larger-than-52-KB UTF-8 document; the browser downloads identical native-platform bytes with a Chinese filename. Downloads reject parent traversal, sibling-prefix paths and escaping links (a native junction on Windows). Held Windows ancestor directories reject rename.
- An unreadable experiment directory leaves other files visible and downloadable, with the failed path shown; restoring permissions and refreshing clears the warning and lists the recovered files.
- Session switches clear previous files and errors while the next request is pending or fails; loading and transport failure do not appear as an empty workspace.
- A child Agent creates a file, returns its result and the parent resumes. Refresh retains one original turn; files remain downloadable on desktop/mobile.
- Stop terminates an actually running local command; refreshing does not repeat it.
- External Skills load native instructions, nested references and script source. A script preserves shebang flags, arguments and cwd, returns exit-7 diagnostics, then another invocation runs longer than 30 seconds and produces a downloadable result. Stop terminates an actual skill-script PID.
- Native Skills resource reads persist original arguments and full results without duplicating executed-script command records. The same journey checks accepted boolean coercion, native returned errors, missing arguments, invalid `args`/`cwd` on a valid executable script, and explicitly injected cancellation at the installed Function boundary. The actual stored validation failures are also rendered in Chromium; normal script execution still has one command record.
- Focused cases cover ordinary research records and standalone analysis without command receipts, unknown-call non-replay and independent continuation, and native session completion without pretending unknown effects succeeded.

The model is a deterministic protocol fixture, not an intelligence or real-provider check. These tests do not establish remote SSH execution, all model protocols, MCP interoperability, long-duration execution or scientific research quality. Real-model and platform-specific acceptance remain separate. `npm run check` itself still runs only frontend lint, types and build; CI also runs the minimal regression suite.

## Local Windows acceptance on 2026-11-08

Before integration, seven local frontend cases pass in 63.343 seconds against disposable PostgreSQL 17 and the local scripted model. Windows directory handles permit write sharing so native Workspace can replace child files, while delete sharing remains disabled. The regression confirms creation, replacement, parent and child contents, Chinese-name download bytes, junction escape rejection, and ancestor rename denial. Combined Skills/frontend validation is recorded separately below.

The fixture uses the production 35-second transport deadline, allows the sequential application cleanup budget, and checks successful lifespan completion after the server thread exits. Windows TLS/RST 10054 and unclosed-transport warnings remain; the transport deadline expires with zero active request tasks and the queue worker then stops. This proves bounded shutdown, not normal closure of every socket.

An isolated native Windows matrix confirms that both the original and current guard permit in-place junction creation on an empty directory through `FILE_WRITE_ATTRIBUTES`. The current guard also permits native creation/editing and blocks ancestor rename with error 32. Sharing flags do not provide an OS sandbox against another process running as the service account.

The separate live browser check uses the existing OpenCode Go subscription and configured SSH host. One real question completes with discovery and two read-only SSH calls, both exit 0. Refresh preserves one turn and three tool calls. A second real session creates, edits and reads a 40-byte Chinese-named file. Its Edge download acceptance is incomplete: download waiting times out, then Computer Use stops because it cannot reliably establish the browser URL. The scripted Chromium journey independently verifies download bytes. Private screenshots and receipts stay outside the repository. See [integration notes](reviews/dsh-web-integration-20261108.md).

## Combined Windows validation on 2026-11-08

The integration of local commit `b552779` and PR #178 head `bf8ad58` passes all 20 minimal cases in 102.661 seconds. It retains both branches' coverage and adds native-loop SSH disconnect presentation. Platform line endings and explicit UTF-8 reads fix the reproduced Windows fixture failures. Frontend checks, Ruff and Pyright pass. A fresh independent source review finds no remaining blocker.

The final integration includes PR #178 head `93119b3` and passes all 21 cases in 113.536 seconds using the default Windows encoding. It covers the matching partial-file-list API/UI contract, real Windows ACL failures, accessible byte-exact downloads, session switching and recovery, plus copy controls, empty fenced code, actual wrap styles, growing/resized composition, retained-fragment streaming, reading position, return-to-bottom, narrow Stop visibility and native Skills read records. Frontend lint/types/build, Ruff, Pyright and whitespace checks pass. Initial failed runs remain in external evidence.

The existing subscription provider also completes a combined task: native SSH exit 0, Chinese file creation/replacement/read and a final Markdown reply. Actual Edge clipboard and narrow-screen checks pass. The initial download-event wait times out, but the complete 34 bytes reach its temporary file. After the user clicks Save, the final real Edge file matches the session source byte-for-byte and by SHA-256; the temporary file disappears. This closes delivery acceptance with manual Save confirmation. See [combined integration evidence](reviews/dsh-skills-integration-20261108.md) and [chat-detail comparison](reviews/chat-detail-fidelity-20261108.md).

The subsequent SSH P2 correction passes the seven-case native boundary journey in 52.293 seconds and all 22 joint Windows cases in 124.087 seconds, with default encoding. It also checks native argument validation before the entrypoint, preserves post-dispatch unknown outcomes and retains public API revocation behavior. Frontend checks, Ruff and Pyright pass. The first full attempt's UI-only initial-read/SSE fixture inconsistency is corrected without changing product behavior; its failure and earlier fixture attempts remain in external evidence. Independent final review finds no remaining issue. Cloud Codex owns the subsequent governance and merge, preserving #178's ancestry before retargeting #179.

The first Linux CI then exposes a missing state-transition wait in the older copy/scroll fixture. Its exact initial GET now shares the SSE snapshot, and scrolling begins only after the jump control disappears; the reading-position assertion is retained. This test-only follow-up passes all 22 Windows cases in 126.072 seconds, plus frontend checks, Ruff and Pyright. Independent review passes. The failed CI is retained, and the final pushed commit's CI is verified separately before cloud handoff.


## Second chat-detail validation on 2026-11-08

The merged `37af529` baseline plus the local chat-detail correction passes all 23 Windows cases in 125.435 seconds with the default encoding, including the final idle Stop condition. The added short-chat case checks the independent 76px header, true-overflow Jump behavior, native file/question/info popovers, idle Stop access, model-settings draft preservation, phone navigation and same-question reopening after X/Escape. The same case preserves an unconfirmed request, checks that new composition is disabled, then clicks the allowed idle Stop and verifies a successful native stop response, persisted stopped state and no model call. Reinstating the old disable condition fails at the enabled assertion; the final complete suite passes. Existing long-stream, clipboard, file, Skills and Stop journeys remain intact.

The first full attempt retains two stale-selector failures and one real narrow overflow: the new grid's implicit column reaches 396px at a 390px viewport. An explicit `minmax(0, 1fr)` column fixes that layout contract; the original overflow assertion remains. Final frontend checks, Ruff, Pyright, whitespace checks and independent source review pass. [Design QA](../design-qa.md) records same-size live Edge comparison and the separate scripted waiting/unknown/reconciliation states. No backend restart or new real provider call is used for this correction.
