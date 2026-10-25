# Browser workspace return verification

Base: `f25c8992f5c286db3cca3554e3c74a255dfe9f82`, stacked on Draft #111.
The platform root workspace remains the homepage. Optional applications retain
query-pointer navigation and reuse the same authentication boundary.

## Executed

- Browser authentication portable tests: 21 passed, zero skipped, 0.570s.
- Frontend: full `npm run check` passed; 442 tests, zero skipped, production build.
- Ruff, Pyright (zero errors/warnings), strict OpenSpec, whitespace passed.
- Official production and complete npm audits: zero vulnerabilities each.
- Real Chromium, actual core business APIs, new isolated PostgreSQL and temporary
  workspaces: demo identity and production-mode local synthetic OIDC, each at
  desktop and narrow viewport. All four journeys passed. Login interrupted a
  resources deep link with a hash; callback restored it; browser back/forward,
  refresh, home, resources, logout/relogin and retired application URL fallback
  passed. No page errors or server errors. Native workers, fixture HTTPS servers,
  browser contexts and newly created databases were cleaned up by fixture exit.
- [Browser results](evidence/browser.json), [login-return screenshot](evidence/login-return.png).

The first portable invocation omitted PYTHONPATH and failed module discovery;
the first browser launch selected an absent Playwright-bundled Chromium. Both
failures were retained in `/tmp/browser-workspace-return-portable-first.log` and
`/tmp/browser-workspace-return-real-first.log`. The corrected invocation supplied
the repository import roots and existing `/usr/bin/chromium`, without altering
assertions, retry behavior or deadlines.

Independent pre-review found no blocking redirect/flow issues and requested
consistent 400 handling for a JSON-escaped isolated surrogate. That boundary and
regression were added; exact final diff review remains a PR gate.

## Limits

This verifies core-only login return, not the new Research demo's full route
journey. The optional demo will receive this change and run its own integration
checks. Synthetic local OIDC over HTTPS is not external production IdP acceptance.
No real model, GPU, new credential configuration or public exposure was used.
