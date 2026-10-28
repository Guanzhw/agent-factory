# Development checks

Run `npm run check` and the relevant dependency audit for frontend changes; run `uv run ruff check platform deployment scripts`, `uv run pyright` and the relevant tests for Python changes. Preserve honest live/unverified labels. The [PR template](../.github/pull_request_template.md) is also a short handoff format; small changes do not need a separate specification.

CI uses Node 24. When reproducing the frontend checks on Node 26, set
`NODE_OPTIONS=--no-experimental-webstorage` for the check process. The pinned DOM
test environment otherwise encounters Node's experimental `localStorage` before
browser storage is installed. The local Node 26 verification used this flag;
the browser application itself does not require it.

## Daily checks and release verification

| Mode | Trigger | Work performed |
| --- | --- | --- |
| `docs` | PR or `main` push changing only recognized documentation | Routing self-tests, whitespace check and the stable `CI summary` result |
| `fast` | Other PRs and `main` pushes | Ubuntu frontend checks, official dependency audits and short Chromium smoke; Python static/boundary checks, explicit Python/PostgreSQL regressions and independent core installation/startup |
| `full` | Manual `workflow_dispatch` for a major release | Complete Linux discovery once in the PostgreSQL job, complete Windows Python discovery, frontend checks on both, Ubuntu audits/browser smoke and independent core installation |

There is no schedule or feature-branch push trigger. To request full verification, open **Actions → Project checks → Run workflow**, select the release branch/ref, and run it. Fast success is daily feedback, not full release acceptance. Full PostgreSQL discovery and required selectors retain the complete Linux behavior checks; the separate Linux Python job performs static and architecture checks without repeating that full execution.

The Ubuntu frontend job runs `npm audit --omit=dev --audit-level=moderate --registry=https://registry.npmjs.org` and the corresponding full audit without `--omit=dev`. Both service errors and moderate-or-higher vulnerabilities fail the step. Production and development dependency results stay separate.

Run the daily selections locally with:

```sh
uv run python scripts/check_fast.py --suite python
# Linux with disposable FACTORY_TEST_DATABASE_URL:
uv run python scripts/check_fast.py --suite postgres
uv run python scripts/check_core_install.py
```

[Explicit groups](../scripts/fast_test_groups.py) retain model selection and current owner/permission checks, real PostgreSQL/process UNKNOWN and lost-acknowledgement recovery, stop evidence, size-one-pool receipt reopening, member publication through HTTP and persistence, and small-tree tamper/deletion checks. Large inventories, multi-service accounting and the remaining regressions still run in full. Both lanes validate selectors against complete discovery, reject empty/missing or cross-lane duplicate selections, execute only selected IDs, and require every selected ID to succeed; skip or expected failure cannot satisfy them. Output reports selected/deferred counts and actual time. `--collect-only` validates selection without claiming execution. Newly discovered tests remain in full even before a fast group selects them.

[Routing](../scripts/ci_scope.py) permits only named root Markdown documents, the PR template and `docs/**/*.md` to take the docs path. Code renamed into docs still requires fast checks; unknown paths, empty diffs and unavailable comparison metadata also use fast. The workflow does not use `paths-ignore`, so **CI summary** always reports the selected mode and checks the expected job results. Failed, cancelled, unexpectedly skipped or missing jobs fail the summary. If branch protection requires the old Windows matrix jobs, its owner should replace those required contexts with **CI summary** before relying on daily routing; this change does not edit protection settings.

## One PostgreSQL execution

With `FACTORY_TEST_DATABASE_URL` pointing to disposable PostgreSQL on Linux, run:

```sh
uv run python scripts/check_postgres.py
```

This uses the same discovery as the ordinary Python entrypoint, covering `platform/tests`. It rejects ambiguous module names, duplicate full test IDs and import errors, executes each discovered ID once and releases completed test instances. Fixture subprocesses receive the same core/deployment/test-fixture import roots. [Required selectors](../scripts/postgres_requirements.py) preserve the five former acceptance groups, add the department self-service classes and pin model/permission/UNKNOWN behavior anchors. Each selector must find tests in discovery; every required ID must actually succeed. A skipped test, skipped class/module, skipped subtest or expected failure cannot satisfy required acceptance. All ordinary failures/errors still fail the run. Other platform skips remain visible and allowed. Counts are diagnostic, never a fixed historical target.

The five old `check_*_postgres.py` commands remain focused local entrypoints; CI does not run them before the full suite. For example, `uv run python scripts/check_postgres.py --group platform_application_boundaries` runs that subset. Preserve existing platform prerequisites, including SSH fixture tools, rather than turning missing requirements into optional coverage. Manual full verification retains a separate Windows compatibility environment; Linux ordinary and database tests execute together in the PostgreSQL job. Its complete log retains case results and skip reasons. Run `uv run python scripts/check_python.py` for complete local Python discovery without a database.

### Optional cost profiling

Use the same disposable database and resource limits, with no competing heavy
checks, to record full-suite or selected-group timings:

```sh
uv run python scripts/profile_tests.py --output /tmp/factory-test-profile
# Optional: --group platform_application_boundaries
```

The profiler delegates discovery and acceptance to `check_postgres`; it does not
retry, change deadlines, or turn skipped required tests into passes. It writes
`summary.json` and `timings.jsonl`: per-case setup/test/teardown/cleanup, separate
class/module fixtures, and selected owned database/process lifecycle helpers.
Helpers overlap their containing phases and must not be added to wall time.
Asyncio runner creation and final loop/executor shutdown occur outside unittest's
case callbacks and remain in total wall time, not individual case phases.
Compare the same observer, resource limits and prerequisites, and preserve failed
runs. Use timings to examine independent behavior and duplicated work, not to
delete tests solely because they are slow or to target a test count.

The Node architecture fixture executes the real checker CLI with `spawnSync`.
A sandbox `EPERM` at that boundary is an environment execution restriction;
retain its failure and run acceptance in an environment permitting local child
processes. Do not skip the CLI assertions or silently substitute direct imports.

## Personal CLI and MCP verification

The [connection lifecycle](PERSONAL_TOOL_CONNECTION_LIFECYCLE.md) and
[implementation contract](PERSONAL_TOOL_IMPLEMENTATION_CONTRACT.md) describe the
implemented boundaries. Dependencies are locked, including official `mcp==2.3.0`;
the MCP adapter uses `ClientSession` and Streamable HTTP. Member endpoints accept
HTTP/HTTPS, local/private/public hosts, IPv6 and custom ports. Credentials are
optional for unauthenticated resources. [Member tools](MEMBER_TOOLS.md) documents
configuration, sharing and use in published applications.

The daily selections in [fast_test_groups.py](../scripts/fast_test_groups.py)
include personal tool connection regressions. For focused adapter/assembly checks
on Linux, without PostgreSQL or live providers:

```sh
PYTHONPATH=platform:deployment:platform/tests uv run python -m unittest \
  test_personal_cli test_personal_cli_process test_personal_mcp \
  test_personal_tools test_personal_tool_execution test_personal_tool_adapter_integration test_member_tool_resources \
  test_personal_tool_assembly.PersonalToolSettingsTests -v
```

CLI tests launch real local synthetic processes. Member commands run once with
their selected arguments, workdir, environment and input/output contract.
Specialized installed adapters retain their integration-specific probes. Tests
distinguish business dispatch from local stop and retained-directory state.
Execution requires POSIX process groups and is verified on Linux; a Windows skip
does not establish Windows CLI support. Debug event loops are intentionally
rejected by the adapter, not silently reconfigured. MCP tests run a local protocol
server and cover stateful/stateless sessions, exact schema/authentication,
revocation, response/log leak rejection, no call replay and bounded session DELETE
authorization/streaming waits. Transport closure does not prove remote stop.
The adapter integration module also runs both local transports through native
`FunctionCall.aexecute()` and the shared wrapper, with an in-memory effect fixture
that verifies DONE receipt replay sends no new process or protocol call.

With an authorized disposable **loopback** `FACTORY_TEST_DATABASE_URL`, run:

```sh
PYTHONPATH=platform:deployment:platform/tests uv run python -m unittest \
  test_personal_tool_assembly.PersonalToolAssemblyPostgresTests \
  test_personal_tool_native_postgres.PersonalToolNativePostgresTests \
  test_member_tool_restart_postgres.MemberToolRestartPostgresTests \
  test_personal_mcp_capacity_postgres.PersonalMCPCapacityPostgresTests -v
```

These classes create and remove their own random databases. Assembly checks run
both independent core and default deployment composition, including authenticated routes,
owner isolation, exact connection pins and retained handles after revocation.
Native tests publish and invoke a declared application through real PostgreSQL,
Agno and the encrypted owner vault, using a deterministic model and inert tool
fixture. They check repeated owner tool calls without new approval, receipt reuse
after reopening services, denial of the next native call after revocation, and
Agno `StopAgentRun` preventing a new model turn after an UNKNOWN effect. They do
not claim that native stop recalls calls already concurrent in the same batch,
or that queue termination proves the original effect stopped.

The member restart class starts a separate Python worker before a new command
exists, creates the command and publishes its materials/application through
member HTTP APIs, and executes the real CLI in that worker through the native
queue. It proves lazy lookup, service restart persistence, original start/receipt
identity and a single command dispatch. A retained-handle case verifies disabled
callers, withdrawn sharing and revoked credentials before another process starts.

The failure/custody case records `{outcome: "failed", stopped: false}` without
completing the UNKNOWN effect, and checks that its occupied capacity still rejects
another submission with HTTP 429 before and after restart. `stopped=True` is
required to settle a failed effect. MCP capacity tests use the local protocol server
to distinguish failures before business dispatch from unresolved local cleanup.
An invocation that has not dispatched `tools/call` releases capacity after its local
tasks, authorization callbacks, SDK contexts and transport finish. Session DELETE is
best effort; an idle remote session does not establish a running business call.
Incomplete local cleanup retains custody, and closing a transport after dispatch
does not prove that the remote business operation stopped. Receipt replay and
capacity checks run both before and after reopening the services.

The browser companion uses the built app and intercepts every API request with
synthetic state:

```sh
npm run build
uv sync --frozen --group browser
uv run --group browser python -m playwright install chromium
uv run --group browser python platform/tests/browser/personal_tools_smoke.py --desktop-only --output /tmp/personal-tool-browser
```

The optional `browser` dependency group pins Playwright; its install command gets
the matching Chromium. The smoke itself requires those installed tools and an
existing build. It follows the real
Resources → connections → personal-tools entry, covering saved-credential setup,
configuration/binding lost-ack recovery, a revoked receipt and an owner change.
It also checks ending a demonstrably unsent binding after descriptor withdrawal,
and settling an explicit credential refusal while preserving the configured tool.
The real core/deployment HTTP tests verify the same structured error codes; browser
fixtures must preserve those actual envelopes. A missing recovery receipt remains
unknown and cannot enable a replacement POST. `--scenario` selects a named flow;
omitting `--desktop-only` retains the optional narrow-viewport cases.
CI runs only `--desktop-only --scenario configured --scenario bind-loss` after
the existing frontend build. It installs just the locked browser group with
`uv sync --frozen --only-group browser`, then uses `uv run --no-sync` for browser
installation and execution. Missing dependencies/browser/build and invalid scene
arguments fail. Other flows remain available through the full command above.
For a locally installed Chromium, pass its path with `--browser` explicitly.
Viewports check horizontal overflow, page errors and unexpected
console errors; deliberately aborted synthetic acknowledgements are recorded
separately. Requests outside the static app and explicitly intercepted APIs,
including WebSockets, are rejected. Browser access from Windows does not imply
Windows CLI execution support.

Test counts are diagnostic, not fixed acceptance targets. Record actual results
in the PR and distinguish local process/protocol, native PostgreSQL and browser
evidence. None of these fixtures calls a real model, runs AutoResearch or verifies
an external vendor's CLI/MCP authentication, OAuth refresh or remote stop semantics.

## Dependency boundaries

```sh
uv run python -m unittest discover -s platform/tests -p test_architecture_checker.py -v
uv run python -m unittest discover -s platform/tests -p test_postgres_checks.py -v
uv run python scripts/check_architecture.py --config scripts/architecture-python.json
node --test scripts/check_web_architecture.test.mjs
node scripts/check_web_architecture.mjs --config scripts/architecture-web.json
```

Both checker CLIs require an explicit map; there is intentionally no passing default. The repository maps above are the single source of truth for paths, public APIs and exact composition exceptions. A Python map uses import search directories and package names, for example this synthetic fixture:

```json
{
  "source_roots": ["src"],
  "core": ["core"],
  "apps": {
    "alpha": {"package": "apps.alpha", "public": ["apps.alpha.api"]},
    "beta": {"package": "apps.beta", "public": ["apps.beta.api"]}
  },
  "composition_roots": ["src/launch.py"]
}
```

The checker parses Python imports, relative imports, package initializers and literal `importlib.import_module`/`__import__` calls without executing code. Recognized but unresolved dynamic imports in owned modules or their reachable helpers fail with a coverage diagnostic; unrelated tests do not acquire this restriction. It does not prove arbitrary reflective loading, runtime permissions, frontend dependencies or package installability; these are not silently reported as verified. Public API calls may encapsulate their app's internals; core traversal never treats app APIs as an exemption. API modules are also checked as origins.

The frontend checker uses the TypeScript parser and module resolver with one `tsconfig` (default `tsconfig.json`). Its map uses project-relative paths: `core` and `source_roots` are directories; each app has `path` and exact `public` files; `composition_roots` are exact files. Import/export, type dependencies, literal dynamic imports, `require`, path aliases and re-exports form edges. Unresolved imports and local source outside the indexed roots report coverage gaps in protected/reachable code. `import.meta.glob` discovery is also an explicit coverage gap; application registration uses explicit imports. The checker does not expand third-party internals, custom loader aliases or `eval`. Both checkers have legal, direct, indirect and composition-bypass fixtures. Exact startup entries may call other exact composition files, as the browser mount calls component assembly. Ordinary core/app callers and similarly named siblings remain protected; startup ownership never extends to them.

## Independent core lifecycle

With disposable `FACTORY_TEST_DATABASE_URL`, run `uv run python scripts/check_core_install.py`. This builds `platform/pyproject.toml` from a temporary stage containing only the core package and its build metadata, installs the wheel and declared dependencies into a new venv, then runs from an empty directory with `python -I`. The runtime receives no provider credentials or checkout import paths. It checks actual Uvicorn lifespan readiness, PostgreSQL health, native worker presence, empty material/application catalogs, absence of research routes/tables, and clean shutdown. Acceptance requires disposable database cleanup too. The probe sends only local GET requests; it never submits a task or requests a model.

Earlier results against the split core wheel are historical; rerun this gate for the core-only revision. It cannot independently prove that every generic-looking implementation belongs in core; pair it with ownership maps and code review.

## Static assembly and compatibility

The default deployment uses core `Settings` and an empty application registration
list. Browser mounting and component assembly remain exact startup files,
`web/main.tsx` and `web/composition.tsx`; ordinary core/application callers cannot
use either as a boundary bypass. The separate `agent-factory-research` and
`web/research-composition.tsx` entries install Research explicitly; application
tests live in `applications/tests`. Generic tests publish explicit checksum
applications and register synthetic adapters through `platform/tests/core_native_fixture.py`.
BYOK and proxy tests retain real native execution with fake provider transports.

Ownership maps cannot prove dynamic wiring; PostgreSQL checks must still exercise
owner/model selection, credential scope/rotation/revocation, original request
identity, UNKNOWN reconciliation, cancellation, usage and restart behavior.
Synthetic credentials and local transports do not establish live provider or
remote compatibility. Historical Research/ORX/Go campaign evidence remains in its
recorded documents and Git history; rerun current application commands against
the explicit Research composition before claiming current acceptance.

## Core-only workspace acceptance

Record exact-revision results separately from previous split-core or Research
passes. Check actual login, logout/relogin, direct URLs and refresh, an empty
application catalog/task list, owner resources and explicitly published test
applications. Research URLs must not expose an application in the core-only
composition; verify them separately with the explicit Research composition.
Run test-only local synthetic
authentication separately; real external production identity remains unverified
unless exercised with its actual protocol/provider.

Use newly created isolated PostgreSQL databases and workspaces, and serialize
heavy database/browser checks. Do not reuse old deployment data for this
verification. Source removal is not authorization to delete old records,
credentials, vault keys, artifacts or backups; permanent deletion awaits a precise
target inventory and confirmation. No current pass is implied by the commands in
this guide; record executed checks and unresolved failures in the Draft PR.

## Why this small scope

This follows [OpenAI's executable-boundary guidance](https://openai.com/index/harness-engineering/), [AGENTS.md directory guidance](https://agents.md/), [a short architecture map](https://matklad.github.io/2021/02/06/ARCHITECTURE.md.html), [incremental work with real verification](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents), and [automated architecture assertions](https://martinfowler.com/articles/fitness-functions-data-products.html). It does not adopt their organizational machinery. Development provider/model preferences belong in a task or acceptance configuration, not a permanent ban on otherwise supported product capabilities.
