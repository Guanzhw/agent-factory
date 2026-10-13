# Development checks

Run `npm run check` and the relevant dependency audit for frontend changes; run `uv run ruff check platform apps/research deployment scripts`, `uv run pyright` and the relevant tests for Python changes. Preserve honest live/unverified labels. The [PR template](../.github/pull_request_template.md) is also a short handoff format; small changes do not need a separate specification.

## Daily checks and release verification

| Mode | Trigger | Work performed |
| --- | --- | --- |
| `docs` | PR or `main` push changing only recognized documentation | Routing self-tests, whitespace check and the stable `CI summary` result |
| `fast` | Other PRs and `main` pushes | Ubuntu frontend checks, Python static/boundary checks, explicit Python and PostgreSQL regressions, and independent core installation/startup |
| `full` | Manual `workflow_dispatch` for a major release | Complete Python discovery on Linux and Windows, frontend checks on both, and complete PostgreSQL discovery with required acceptance |

There is no schedule or feature-branch push trigger. To request full verification, open **Actions → Project checks → Run workflow**, select the release branch/ref, and run it. Fast success is daily feedback, not full release acceptance. Full runners and their required acceptance selectors remain unchanged.

Run the daily selections locally with:

```sh
uv run python scripts/check_fast.py --suite python
# Linux with disposable FACTORY_TEST_DATABASE_URL:
uv run python scripts/check_fast.py --suite postgres
uv run python scripts/check_core_install.py
```

[Explicit groups](../scripts/fast_test_groups.py) retain model selection and current owner/permission checks, real PostgreSQL/process UNKNOWN and lost-acknowledgement recovery, stop evidence, size-one-pool receipt reopening, member publication through HTTP and persistence, and small-tree tamper/deletion checks. Large inventories, multi-service accounting, scientific multi-database campaigns and the remaining regressions still run in full. Both lanes validate selectors against complete discovery, reject empty/missing or cross-lane duplicate selections, execute only selected IDs, and require every selected ID to succeed; skip or expected failure cannot satisfy them. Output reports selected/deferred counts and actual time. `--collect-only` validates selection without claiming execution. Newly discovered tests remain in full even before a fast group selects them.

[Routing](../scripts/ci_scope.py) permits only named root Markdown documents, the PR template and `docs/**/*.md` to take the docs path. Code renamed into docs still requires fast checks; unknown paths, empty diffs and unavailable comparison metadata also use fast. The workflow does not use `paths-ignore`, so **CI summary** always reports the selected mode and checks the expected job results. Failed, cancelled, unexpectedly skipped or missing jobs fail the summary. If branch protection requires the old Windows matrix jobs, its owner should replace those required contexts with **CI summary** before relying on daily routing; this change does not edit protection settings.

## One PostgreSQL execution

With `FACTORY_TEST_DATABASE_URL` pointing to disposable PostgreSQL on Linux, run:

```sh
uv run python scripts/check_postgres.py
```

This uses the same discovery as the ordinary Python entrypoint, covering `platform/tests` and `apps/research/tests/python`. It rejects ambiguous module names, duplicate full test IDs and import errors in either tree, executes each discovered ID once and releases completed test instances. Fixture subprocesses receive the same core/app/deployment import roots. [Required selectors](../scripts/postgres_requirements.py) preserve the five former acceptance groups, add the department self-service classes and pin model/permission/UNKNOWN behavior anchors. Each selector must find tests in discovery; every required ID must actually succeed. A skipped test, skipped class/module, skipped subtest or expected failure cannot satisfy required acceptance. All ordinary failures/errors still fail the run. Other platform skips remain visible and allowed. Counts are diagnostic, never a fixed historical target.

The five old `check_*_postgres.py` commands remain focused local entrypoints; CI does not run them before the full suite. For example, `uv run python scripts/check_postgres.py --group platform_application_boundaries` runs that subset. Preserve existing platform prerequisites, including SSH fixture tools, rather than turning missing requirements into optional coverage. Windows/Linux compatibility jobs remain separate environments in manual full verification. Run `uv run python scripts/check_python.py` for complete local Python discovery.

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

The frontend checker uses the TypeScript parser and module resolver with one `tsconfig` (default `tsconfig.json`). Its map uses project-relative paths: `core` and `source_roots` are directories; each app has `path` and exact `public` files; `composition_roots` are exact files. Import/export, type dependencies, literal dynamic imports, `require`, path aliases and re-exports form edges. Unresolved imports and local source outside the indexed roots report coverage gaps in protected/reachable code. It does not expand third-party internals, custom loader aliases, `eval` or bundler-generated dependencies. Both checkers have legal, direct, indirect and composition-bypass fixtures. Exact startup entries may call other exact composition files, as the browser mount calls component assembly. Ordinary core/app callers and similarly named siblings remain protected; startup ownership never extends to them.

## Independent core lifecycle

With disposable `FACTORY_TEST_DATABASE_URL`, run `uv run python scripts/check_core_install.py`. This builds `platform/pyproject.toml` from a temporary stage containing only the core package and its build metadata, installs the wheel and declared dependencies into a new venv, then runs from an empty directory with `python -I`. The runtime receives no provider credentials or checkout import paths. It checks actual Uvicorn lifespan readiness, PostgreSQL health, native worker presence, empty material/application catalogs, absence of research routes/tables, and clean shutdown. Acceptance requires disposable database cleanup too. The probe sends only local GET requests; it never submits a task or requests a model.

This gate passed against the split core wheel. It cannot independently prove that every generic-looking implementation belongs in core; pair it with ownership maps and code review.

## Static assembly and compatibility

Both ownership maps pass after the split. Research preparation/training assembly requires an explicit `app_factory`; the deployment CLI supplies `agent_factory_server.main.create_app`. Reusable research code never imports the server. Browser mounting and component assembly remain two exact startup files, `web/main.tsx` and `web/composition.tsx`; ordinary core/app callers cannot use either as a boundary bypass.

The full PostgreSQL run also exercises dynamic service wiring, which import maps
cannot prove. Research delegation/cleanup live in application subclasses selected
by static composition; the core has no research-table fallback. Regression cases
cover original scientific placement receipts, member-source handoffs that retain
receiver approval, and cancellation between effect reservation and storage
preparation. Only positive never-dispatched and cleanup evidence can settle that
cancellation; an ambiguous launch remains UNKNOWN.

Ordinary model/ORX fixtures and Go diagnostics use member self-service while retaining owner, selected-model, revocation, UNKNOWN and stop-proof checks. Explicit historical approval tests remain compatibility coverage. Legacy Go preflight and failure recovery stay in the research adapter; shared model dispatch does not load a campaign. Deterministic acceptance uses local transports and synthetic credentials, and does not establish live model/remote compatibility or encode a permanent provider/model ban.

## Why this small scope

This follows [OpenAI's executable-boundary guidance](https://openai.com/index/harness-engineering/), [AGENTS.md directory guidance](https://agents.md/), [a short architecture map](https://matklad.github.io/2021/02/06/ARCHITECTURE.md.html), [incremental work with real verification](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents), and [automated architecture assertions](https://martinfowler.com/articles/fitness-functions-data-products.html). It does not adopt their organizational machinery. Development provider/model preferences belong in a task or acceptance configuration, not a permanent ban on otherwise supported product capabilities.
