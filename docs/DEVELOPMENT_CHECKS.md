# Development checks

Run `npm run check` and the relevant dependency audit for frontend changes; run `uv run ruff check platform scripts` and `uv run pyright` for Python changes. Preserve honest live/unverified labels. The [PR template](../.github/pull_request_template.md) is also a short handoff format; small changes do not need a separate specification.

## One PostgreSQL execution

With `FACTORY_TEST_DATABASE_URL` pointing to disposable PostgreSQL on Linux, run:

```sh
uv run python scripts/check_postgres.py
```

This discovers the suite once, retains one test instance per full unittest ID, and executes once. [Required selectors](../scripts/postgres_requirements.py) preserve the five former acceptance groups plus a few model/permission/UNKNOWN behavior anchors. Each selector must find tests in discovery; every required ID must actually succeed. A skipped test, skipped class/module, skipped subtest or expected failure cannot satisfy required acceptance. All ordinary failures/errors still fail the run. Other platform skips remain visible and allowed. Counts are diagnostic, never a fixed historical target.

The five old `check_*_postgres.py` commands remain focused local entrypoints; CI does not run them before the full suite. For example, `uv run python scripts/check_postgres.py --group platform_application_boundaries` runs that subset. Preserve existing platform prerequisites, including SSH fixture tools, rather than turning missing requirements into optional coverage. Windows/Linux compatibility jobs remain separate environments.

CI runs on pull requests, pushes to `main`, and explicit workflow dispatch. A feature-branch push with an open PR therefore starts one workflow, while merged code is still checked on `main`.

## Dependency checker preparation

```sh
uv run python -m unittest discover -s platform/tests -p test_architecture_checker.py -v
uv run python -m unittest discover -s platform/tests -p test_postgres_checks.py -v
uv run python scripts/check_architecture.py --root /path/to/project --config /path/to/ownership.json
node --test scripts/check_web_architecture.test.mjs
node scripts/check_web_architecture.mjs --root /path/to/project --config /path/to/web-ownership.json
```

The last command requires an agreed map; there is intentionally no passing default for this repository yet. A map uses import search directories and package names, for example this synthetic fixture (not a repository baseline):

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

The frontend checker uses the TypeScript parser and module resolver with one `tsconfig` (default `tsconfig.json`). Its map uses project-relative paths: `core` and `source_roots` are directories; each app has `path` and exact `public` files; `composition_roots` are exact files. Import/export, type dependencies, literal dynamic imports, `require`, path aliases and re-exports form edges. Unresolved imports and local source outside the indexed roots report coverage gaps in protected/reachable code. It does not expand third-party internals, custom loader aliases, `eval` or bundler-generated dependencies. Both checkers have legal, direct, indirect and composition-bypass fixtures. A composition root may wire application internals; it cannot exempt its callers or similarly named siblings.

Repository wiring remains pending the actual app/core split. No migration allowlist has been added. The core-only smoke must use an isolated, non-editable installation with no app source available and complete startup/health/shutdown; it is not implemented in this preparation change.

Known baseline coupling at `615a23f` (migration work, never passing exceptions):

| Existing dependency/responsibility | Required destination |
| --- | --- |
| `agent_factory.main` imports `orx_tools`, `orx_literature_tools`, `orx_experiment_tools` and initializes their schema/tools | Research installer called by the exact deployment composition file |
| `agent_factory.main` imports `autoresearch`, `openresearch_workspace`, `research_runtime` and installs their routers/services | Research application assembly and services |
| `agent_factory.config.Settings` contains research evaluators, presets, profile factories and OpenResearch packages | Research settings |
| `agent_factory.store.Store` carries research session, child, runtime and evaluation services | Research services; core retains only narrow execution lifecycle hooks |
| `web/App.tsx` imports and renders concrete research screens | Research frontend selected in `web/composition.tsx` through static component slots |
| Ordinary-flow fixtures in `ApplicationContextNativePostgresTests`, `ManagedWorkspacePostgresTests`, `PersonalOrxPostgresTests` and `PersonalModelsPostgresTests` still assert legacy review/owner-submission admission | Migrate normal fixtures to member self-service while retaining owner/model/UNKNOWN assertions; historical approvals are compatibility cases, not current product requirements |

The directory contract is maintained only in [ARCHITECTURE.md](../ARCHITECTURE.md). This table is a migration status list, not a second ownership map; remove resolved rows when integrating the split. Deterministic acceptance uses local transports and synthetic credentials. It must not send real model requests or encode a permanent provider/model ban.

## Why this small scope

This follows [OpenAI's executable-boundary guidance](https://openai.com/index/harness-engineering/), [AGENTS.md directory guidance](https://agents.md/), [a short architecture map](https://matklad.github.io/2021/02/06/ARCHITECTURE.md.html), [incremental work with real verification](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents), and [automated architecture assertions](https://martinfowler.com/articles/fitness-functions-data-products.html). It does not adopt their organizational machinery. Development provider/model preferences belong in a task or acceptance configuration, not a permanent ban on otherwise supported product capabilities.
