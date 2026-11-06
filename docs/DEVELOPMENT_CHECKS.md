# Validate a change

Use a disposable database and workspace for execution checks. Keep existing user data and credentials out of test fixtures. Record the exact commit, environment, results, and skip reasons in the PR.

## Run the checks relevant to the change

For Python changes, run the static checks and focused tests:

```sh
uv run ruff check platform deployment applications scripts
uv run pyright
uv run python scripts/check_fast.py --suite python
```

For frontend changes, run the frontend checks and both dependency audits:

```sh
npm run check
npm audit --omit=dev --audit-level=moderate --registry=https://registry.npmjs.org
npm audit --audit-level=moderate --registry=https://registry.npmjs.org
```

CI uses Node 24. On Node 26, set `NODE_OPTIONS=--no-experimental-webstorage` for the check process. The pinned DOM test environment otherwise encounters Node's experimental `localStorage`.

For a full Python discovery run, use:

```sh
uv run python scripts/check_python.py
```

The collector discovers `platform/tests` and `applications/tests`. Database-dependent cases can skip without a configured test database. A skip is not execution evidence.

## Run PostgreSQL checks

Set `FACTORY_TEST_DATABASE_URL` to an authorized disposable PostgreSQL server. Then run the focused daily selection or the complete database suite:

```sh
uv run python scripts/check_fast.py --suite postgres
uv run python scripts/check_postgres.py
```

Use `--group` with a group from [postgres_requirements.py](../scripts/postgres_requirements.py) when investigating one behavior. Required selectors must resolve to actual tests and pass. The runner rejects missing selectors, ambiguous modules, duplicate IDs, and failures. Record other skip reasons separately.

Run the standalone-core boundary after changing packaging or composition:

```sh
uv run python scripts/check_core_install.py
```

This check builds the core wheel from core source, installs it into a fresh environment, and starts it from an empty directory. It checks PostgreSQL health, native workers, application independence, and cleanup. It does not submit a research task or call a model.

## Check dependency direction

Run both checked ownership maps:

```sh
uv run python scripts/check_architecture.py --config scripts/architecture-python.json
node scripts/check_web_architecture.mjs --config scripts/architecture-web.json
```

If a checker changes, run its regression tests too:

```sh
uv run python -m unittest discover -s platform/tests -p test_architecture_checker.py -v
node --test scripts/check_web_architecture.test.mjs
```

The maps define packages, public interfaces, and exact composition exceptions. Static import checks do not prove that runtime wiring selects the correct model or preserves resource ownership. Use application tests for those behaviors.

## Verify native Windows execution

From a checkout with locked dependencies, run:

```powershell
$env:PYTHONPATH = 'platform;deployment;platform/tests;applications;applications/tests'
.\.venv\Scripts\python.exe -m unittest test_research_session_tools test_personal_cli_process test_windows_ssh_process -v
```

These tests exercise file operations, real commands, pipes, and owned Job Objects. Inspect skipped OS or privilege-dependent cases. Successful browser access alone does not prove Windows command execution.

With disposable PostgreSQL configured, run the restart cases:

```powershell
.\.venv\Scripts\python.exe -m unittest test_research_windows_restart -v
```

The restart cases distinguish an unknown command outcome, a persisted receipt before reply, and a completed session reopened before a new turn. They use a scripted provider. They do not establish real-model behavior or prove every active-process crash scenario.

For server exit behavior, use the targeted checks in [Shutdown](SHUTDOWN.md). Idle shutdown and shutdown after research are distinct scenarios.

## Verify browser behavior and real models separately

Build the app and install the optional browser tools:

```sh
npm run build
uv sync --frozen --group browser
uv run --group browser python -m playwright install chromium
```

The daily personal-tools smoke uses intercepted synthetic API responses:

```sh
uv run --group browser python platform/tests/browser/personal_tools_smoke.py --desktop-only --output ./browser-results
```

It verifies UI behavior, not a real provider. A live research acceptance must also verify actual authentication, the selected model, tool execution, visible results, original-request recovery, and stop evidence. Record any unverified artifact download, remote environment, or capacity claim.

## Select the CI scope

The [Project checks workflow](../.github/workflows/ci.yml) and [scope classifier](../scripts/ci_scope.py) define the exact jobs:

- Recognized documentation-only changes use `docs` checks.
- Other pull requests and main pushes use `fast` checks.
- Manual `workflow_dispatch` selects `full` verification.

Use the final commit's results. A prior commit's pass or a canceled run does not establish the current result. Full verification runs Linux PostgreSQL discovery, Windows compatibility, frontend checks, browser smoke, audits, and independent core installation according to the workflow.

For test-cost investigation, use `scripts/profile_tests.py`. Its reports preserve overlapping setup, test, and cleanup timings. A slow test is not by itself a reason to delete it.

## Report the result

Use the [PR template](../.github/pull_request_template.md). State what changed, which checks ran, what those checks establish, and what remains unverified. Keep historical acceptance in its dated record. The current product selects Research by default; core-only composition checks remain package tests, not a second user journey.
