# Controlled schedule diagnostics browser acceptance

`run_schedule_diagnostics_acceptance.py` reproduces the desktop and mobile
acceptance from this checkout. It is a test runner, not a deployment launcher.

Prerequisites:

- Project Python dependencies and Playwright with Chromium installed.
- Frontend assets built with `npm run build`.
- An explicitly authorized **loopback PostgreSQL** server whose test role can
  create databases. The runner rejects remote hosts and URL query overrides.
- An unused output directory. Run heavy acceptance serially with other browser
  and PostgreSQL suites.

Run with a synthetic local test database URL; never paste production credentials:

```sh
python scripts/run_schedule_diagnostics_acceptance.py \
  --fixture-database-url postgresql+psycopg://localhost/factory_test \
  --output-dir ./acceptance-output/schedule-diagnostics
```

If Chromium is installed in a nondefault location, set
`PLAYWRIGHT_BROWSERS_PATH` to that installation. The script resolves project and
fixture imports relative to its Git checkout; it requires no scratch runner or
previous test evidence. `--help` performs no database or browser work.

The runner creates and later drops only a randomly named disposable database,
uses a temporary workspace, and runs a loopback HTTPS server with temporary TLS.
It does not install certificates or change host trust. Browser TLS exceptions
are scoped to the isolated test contexts. Inherited provider/authentication
environment variables are removed before application imports.

Real mock login, independent plan review, and the schedule editor create each
paused schedule. A fixture-only, single-thread driver then takes actual native
claims and produces authorization, advisory-lock, pause, and changed-claim
refusals. It never exposes a control route. The poll interval is explicitly
lengthened within this disposable fixture so the controlled claim driver is the
only actor advancing its test clocks. This does **not** verify production
wall-clock scheduling.

The browser checks finite Chinese reason labels, the 30-day/100-record retention
notice, three read-only refreshes, reloading original record IDs, and Bob's
isolation. Repeating a blocked claim preserves the original diagnostic ID and
observation time. Legacy raw audit detail must not appear. SQL checks require
zero tasks, occurrences, and native jobs throughout. Screenshots must have no
horizontal overflow; page and unexpected console errors fail acceptance.

`evidence.json` records controlled-fixture provenance, scenario results, and
cleanup completion. A zero exit status and `ok: true` mean the whole run passed.
A failed run preserves finite failure stages and screenshots without recording
cookies, tokens, form bodies, or raw exceptions. `cleanupComplete` is deliberately
conservative if a failure interrupts orchestration. The runner does not claim
live provider, production identity, target capacity, or production timer proof.

To inspect an already prepared isolated server without creating another fixture,
use `accept_schedule_diagnostics_browser.py` with `--base-url`, `--schedule-id`,
and `--output-dir`. That lower-level CLI does not manufacture refusal records.
