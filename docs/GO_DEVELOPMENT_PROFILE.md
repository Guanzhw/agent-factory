# Go development product profile

This stage connects the prior isolated adapter to the actual Factory material,
application, immutable-plan, native-queue, tool, receipt, artifact and PostgreSQL
usage-ledger path. It is an explicitly selected coding-development profile.
Production model bindings and research-provider selection remain independent.

## Operator setup and governed selection

`Settings(development_profile="opencode-go", demo=True)` (or
`FACTORY_DEVELOPMENT_PROFILE=opencode-go`) installs exact model registrations and
nominal pricing contracts. The default is `disabled`; non-demo settings reject
this profile. Enabling it neither publishes materials nor selects a model.

Use `go_development.material_drafts()` through normal separate-author/reviewer
publication, or its `publish_go_development_models` helper. Publish
`application_definition(...)` through the existing application draft/review API,
then explicitly select `go-development-checksum` and one exact model mode:

- `deepseek-v4-flash`: Chat Completions.
- `gpt-6-luna`: Responses, with its own parser and tool encoding.

The unversioned `deepseek-flash` alias is not selected. The application is excluded
from automatic discovery, including a republished definition marked as default.
Only the checksum coding fixture tool and standalone task scope are admitted;
delegation, substituted materials, other apps and arbitrary endpoints are denied.
The normal Factory API returns plan/receipt/task/artifact/usage evidence.

Install an owner-scoped `trusted_model_binding` with a `GoDevelopmentHandle` in
operator settings, and bind it through the ordinary owner connection API. The
handle remains outside all materials, plans, prompts, receipts and API payloads.
Fresh authority checks validate exact connection/material revisions before each
provider call and again before returned tool intent can execute.

## Controlled transport only

The current product profile executes only `mode="fixture"`. It accepts exact
`httpx.MockTransport` or exact `GoLoopbackTransport` objects, not arbitrary network
transports or subclasses. The latter requires an explicit HTTP port on literal
127.0.0.1 or ::1, rewrites only the two fixed Go POST routes, drops Authorization,
and disables environment proxies, redirects and transport retries. Its credential
is a fixed non-secret substitute. No real environment key is read by this setup.

Provider HTTP uses bounded SSE. The native queue remains non-streaming and receives
one complete authoritative model result before Agno executes tool calls. This
proves wire streaming, not progressive token display in the frontend. The truthful
User-Agent is fixed; `x-opencode-session` equals the original Factory task ID.

Missing, inconsistent or partial usage stops the response before tools execute.
Unknown attempts retain their durable token and positive amount holds across an
application restart. Completed incurred usage settles before a later authority
check, so revocation cannot erase cost. Only fixture 503 errors may have one
explicit native retry; each HTTP attempt gets its own reservation. Authentication,
quota and unknown usage are not retried. Final model failure writes a durable
Go-only protected failure; queue replay cannot reset the model retry allowance.

Nominal nonzero catalogue rates exercise reservations and settlement; they are not
account invoices. The serialized-input admission envelope includes tool schemas,
and enforces output/deadline/retry bounds before dispatch. It is a controlled
fixture contract, not a verified live tokenizer or cache/time-dependent tariff.

## Live gate and minimum missing evidence

`mode="subscription"` always fails preflight with `GO_LIVE_VALIDATION_PENDING`,
even if a supplied billing callback would return true. Neither billing nor
credential callback is invoked. No real key was read and no authenticated Go
request was sent in this stage.

The [official Go documentation](https://opencode.ai/docs/go/) describes coding-agent
use and the **Use balance** option. A zero balance does not establish that future
requests cannot incur subscription-external charges. Required next evidence:

1. In the account console, inspect Go subscription status, both selected models'
   availability/allowance, and confirm **Use balance is disabled**. Provide only a
   redacted statement or image showing these settings; never include API keys,
   account identifiers, payment details or authorization headers.
2. Establish whether disabled balance fully excludes all subscription-external
   charges for these requests. If the console/docs do not establish this, obtain
   provider clarification; do not infer it from a zero balance.
3. Before enabling live code, implement a trusted current account verifier,
   verified live input/accounting bounds and a persistent total cap of three short
   requests per model, retry zero, timeout at most 60 seconds, synthetic/public
   coding input only. Stop on auth, quota or unknown usage. These gates are not
   implemented or satisfied by this fixture phase.

Production identity and non-toy research inputs have a separate concise
[decision list](PRODUCTION_DECISIONS.md). This development profile cannot be used
as implicit approval for scientific or production traffic.

## Reproduction

With the repository's pinned environment and a disposable PostgreSQL database:

```sh
env -u OPENCODE_GO PYTHONPATH=platform:platform/tests .venv/bin/python -m unittest -v test_opencode_go test_go_development_profile test_go_usage
# FACTORY_TEST_DATABASE_URL must point to the disposable synthetic database.
env -u OPENCODE_GO PYTHONPATH=platform:platform/tests .venv/bin/python -m unittest -v test_go_product_postgres
```

The product tests publish/review real materials and an application, bind the
owner, choose a model, submit a native queued task, serve actual loopback HTTP SSE,
execute checksum, download its artifact and inspect durable usage. Error cases
cover quota, partial streams, unknown usage/restart, revocation after a tool-call
SSE delta, successful 503 retry and exhausted retry budget. No fixture result is
live Go compatibility or billing evidence.

Local acceptance: 38 focused offline tests passed; all seven actual HTTP/PostgreSQL
product cases passed in 43.926 seconds. Frontend check passed 64 tests plus build,
lint and typecheck; Ruff/Pyright passed and npm audit reported zero vulnerabilities.
The earlier application-scope setup failures and queue quota replay failure were
fixed and retained in the handoff history. Full regression and final exact-SHA CI
are reported on the stage draft PR.
