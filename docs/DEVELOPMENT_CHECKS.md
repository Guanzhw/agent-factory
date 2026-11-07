# Development checks

The old test suite was deleted at the user's request on 2026-11-07. The user subsequently requested minimal feature-based regression coverage using Ponytail. The new suite has four browser cases and three focused review regressions; it does not restore the old tests or their implementation constraints.

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
- A separate UI snapshot case covers missing events, transport EOF and reconnection, terminal unknown results, later reconciliation, one row per call ID, Markdown tables, and narrow screens. These snapshots are synthetic and do not prove provider or SSH connectivity.
- Native file creation and replacement produce a larger-than-52-KB UTF-8 document; the browser downloads identical native-platform bytes with a Chinese filename. Downloads reject parent traversal, sibling-prefix paths and escaping links (a native junction on Windows). Held Windows ancestor directories reject rename.
- A child Agent creates a file, returns its result and the parent resumes. Refresh retains one original turn; files remain downloadable on desktop/mobile.
- Stop terminates an actually running local command; refreshing does not repeat it.

The model is a deterministic protocol fixture, not an intelligence or real-provider check. These tests do not establish Windows compatibility, remote SSH execution, all model protocols, MCP interoperability, long-duration execution or scientific research quality. Real-model and platform-specific acceptance remain separate. `npm run check` itself still runs only frontend lint, types and build; CI also runs all seven regression cases.

## Local Windows acceptance on 2026-11-08

All seven cases pass in 63.343 seconds against disposable PostgreSQL 17 and the local scripted model. Windows directory handles now permit write sharing so native Workspace can replace child files, while delete sharing remains disabled. The regression confirms creation, replacement, parent and child contents, Chinese-name download bytes, junction escape rejection, and ancestor rename denial.

The fixture uses the production 35-second transport deadline, allows the sequential application cleanup budget, and checks successful lifespan completion after the server thread exits. Windows TLS/RST 10054 and unclosed-transport warnings remain; the transport deadline expires with zero active request tasks and the queue worker then stops. This proves bounded shutdown, not normal closure of every socket. In-place reparse mutation was not established by the extra handle matrix.

The separate live browser check uses the existing OpenCode Go subscription and configured SSH host. One real question completes with discovery and two read-only SSH calls, both exit 0. Refresh preserves one turn and three tool calls. A second real session creates, edits and reads a 40-byte Chinese-named file. Its Edge download acceptance is incomplete: download waiting times out, then Computer Use stops because it cannot reliably establish the browser URL. The scripted Chromium journey independently verifies download bytes. Private screenshots and receipts stay outside the repository. See [integration notes](reviews/dsh-web-integration-20261108.md).
