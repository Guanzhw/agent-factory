# Runnable development implementation checkpoint

Branch: `coord/schedule-diagnostics-checkpoint-20261004`, based on accepted PR33
`e0f74ec330b4f11929be49b4d260acbe1747856f`. The final draft PR acceptance receipt
records the exact tested head SHA and both CI observations. Check out that SHA,
not a moving branch, when reproducing the receipt. No PR is merged or deployed.

## Start a persistent local development instance

Use Linux, Python3.12+, Node24+, uv and an existing, dedicated PostgreSQL database.
The controlled comparison profile uses Linux process limits and fixed synthetic
fixtures. It needs no model key, OpenCode credential, real IdP or external source.
Use a dedicated persistent workspace; never point this launcher at production.

```bash
git checkout <exact-tested-head-from-the-draft-PR>
npm ci --ignore-scripts
uv sync --frozen
npm run build
# Set FACTORY_DATABASE_URL to your dedicated PostgreSQL database privately.
# Example for an existing local socket database using the current OS role:
export FACTORY_DATABASE_URL='postgresql+psycopg:///agent_factory_development'
.venv/bin/python scripts/run_development_factory.py \
  --public-origin https://127.0.0.1:3443 \
  --workspace "$PWD/.local/development-workflows" \
  --profile controlled-workflows \
  --initialize-controlled-fixtures
```

The database must already exist. The launcher neither creates an external account
nor destroys your database/workspace. It serves the built frontend and API at the
printed loopback HTTPS origin. Accept only this local temporary self-signed
certificate in the browser; no system trust change is needed. Stop with Ctrl+C.
For subsequent starts use the same database/workspace and omit
`--initialize-controlled-fixtures`. Default `--profile basic` retains the original
basic demo and does not install the extra workflow fixtures.

Initialization explicitly publishes synthetic materials and application versions
through the normal two distinct mock-manager review identities and binds initial
Alice/Bob connections using stable command IDs. This is fixture preparation, not
evidence of independent human approval. It never approves a task plan, grants a
revoked role, reactivates withdrawn material, or replaces a revoked connection.
Task plans still require their normal current review and permission checks.

## Supported development journeys

The mock-login page offers Alice, Bob, Manager and a second Manager/reviewer.
Use separate browser profiles or log out between identities.

1. **Material/application governance:** managers create drafts, inspect versions
   and request publication; the other manager reviews them. Alice discovers only
   published compatible definitions and composes an immutable reviewed plan.
2. **Native execution/recovery:** approve the exact proposed plan, start one task,
   inspect events/questions/artifacts, cancel within scope, and reopen original
   proposal/plan/task receipts after reload. Reads do not create replacements.
3. **Synthetic source → controlled synthesis:** select the clearly labeled
   development source application and your own source connection. After review
   and execution, inspect its source report, fix a source snapshot, and compose
   the controlled synthesis application with your own fixture model connection.
   Review that new plan independently. The source HTTP protocol is mocked;
   citations are structural fixture evidence, never real research conclusions.
4. **Baseline/candidate comparison:** choose one fixed synthetic candidate mode
   in the comparison panel, review its pinned input/plan, and run the bounded
   paired evaluator. Inspect matched baseline/candidate metrics and report hash.
   No arbitrary user code, scientific dataset or shell command is accepted.
5. **Schedules:** managers prepare a reviewed ready plan, preview cron/timezone,
   create the clock paused, and explicitly enable/edit/pause it. Native accepted
   occurrences retain original task/run identity. The separate rejection panel
   reads bounded owner-scoped diagnostics even when an editor is pending or run
   permission has been revoked, provided current read permission remains.
6. **Owner isolation and storage:** Bob cannot inspect Alice's private plans,
   tasks, snapshots or diagnostics. Use normal connection revocation and the
   storage/quarantine views to inspect their scoped state.

Remote attachment, cross-host cancellation and aggregate cgroup enforcement are
implemented separately but not automatically configured by this local profile.
Historical authorized Go development calls do not select a production provider;
this launcher does not read or use that subscription.

## Checkpoint verification

Local full Python:1220 tests,846 passed and374 intentionally skipped without the
PG test environment. Targeted real PG/native validation separately exercised all
nine diagnostic cases and both persistent-development cases. Frontend196 tests,
lint/types/build, Ruff, Linux/Windows Pyright and production dependency audit pass.
Controlled desktop/mobile browser diagnostics passed and were reproduced using
only the checked-in runner. The actual CLI passed two HTTPS/Chromium mock-login
starts with the same three application version/hash pins after restart.

Independent code/evidence review found no remaining blocker in the selected
bounded development scope. Exact-head Linux/Windows and full PostgreSQL CI is a
separate final gate recorded in the draft PR; local skipped tests are not counted
as passing PG acceptance. Initial fixture-only failures remain in the audit.

## Remaining inputs and acceptance

See [the final requirements audit](V03_FINAL_REQUIREMENT_AUDIT.md) and
[closure map](IMPLEMENTATION_CLOSURE_MAP.md). Real scientific provider protocol,
retry/usage/pricing policy and non-toy dataset/evaluator/reviewed change scope
must be selected before the remaining adapters can be implemented and validated.
These are input-dependent **code and validation**, not merely missing keys.

Production also requires actual IdP/TLS and role mappings, target Linux/runtime
and receiver configuration, real kernel delegation tests, physical cross-host
acceptance, and a sustained approximately20-user workload on the chosen32-core/
64-GB or54-core/192-GB machine. Disk thresholds, monitoring and backup/restore
objectives need operator acceptance. Local mocks, process fixtures and CI do not
certify those environments or scientific validity.

Optional scheduling policy extensions and machine provisioning are not implied
requirements for this checkpoint. Continue when those specific policies or real
inputs are supplied; do not infer unlimited new scope from a completed fixture.
