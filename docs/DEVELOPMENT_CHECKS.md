# Development checks

The user requested deletion of the entire existing test suite on 2026-11-07. Test files, dedicated fixtures, acceptance scripts, runners and test-only dependencies have been removed. CI runs static checks and the frontend build. It does not establish functional acceptance.

## Static checks and build

```sh
uv run ruff check platform deployment applications
uv run pyright
npm run check
```

`npm run check` runs lint, TypeScript checking and the production build. It runs no tests.

## Actual use

Review working startup, model configuration, conversation, understandable progress and results, file operations, long tasks, subassistants and Stop through the application itself. Record what was actually exercised and any failures. Keep credentials and user data outside the repository. Do not create a new test suite until the user asks.

A previous revision's test or acceptance result applies only to that revision. Historical reports may reference deleted scripts. Do not equate static checks, a build, or an earlier pass with completed product acceptance.
