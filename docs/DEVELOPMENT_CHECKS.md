# Development checks

The old test suite was deleted at the user's request on 2026-11-07. The user subsequently requested minimal feature-based regression coverage using Ponytail. The new suite has two browser journeys; it does not restore the old tests or their implementation constraints.

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

- Ordinary login opens chat; model configuration through Settings selects the model used by the Agent.
- A chat draft survives a settings visit. A streamed response and native tool calls travel through the actual model HTTP adapter and Agno queue.
- A configured CLI's exit 7 preserves stdout/stderr and the Agent continues with another call.
- The Agent receives the configured SSH server reference from discovery without user input.
- Native file editing produces a larger-than-52-KB UTF-8 document; the browser downloads identical bytes with a Chinese filename.
- A child Agent creates a file, returns its result and the parent resumes. Refresh retains one original turn; files remain downloadable on desktop/mobile.
- Stop terminates an actually running local command; refreshing does not repeat it.

The model is a deterministic protocol fixture, not an intelligence or real-provider check. These tests do not establish Windows compatibility, remote SSH execution, all model protocols, MCP interoperability, long-duration execution or scientific research quality. Real-model and platform-specific acceptance remain separate. `npm run check` itself still runs only frontend lint, types and build; CI also runs the two journeys.
