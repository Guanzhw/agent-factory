# Current delivery and review index

## Latest accepted local milestone — 2026-10-07

See [first real local baseline acceptance](RESEARCH_BASELINE_ACCEPTANCE.md) for the owner-verified real result at
09:48 UTC, exact PR54 runner/sealed PR50 runtime, released custody and remaining
original-plan priorities. The older current-scope wording below predates that
selected local baseline; production, department capacity and separate-host
acceptance remain distinct. Personal-agent/24-hour work remains deferred in
[PR51](https://github.com/Guanzhw/agent-factory/pull/51).

## Current scope — 2026-10-04

See the [current scope reconciliation](V03_SCOPE_RECONCILIATION.md)
and [PR28 application workflow audit](V03_APP_GAP_AUDIT.md) for implementation,
remaining flows and historical evidence boundaries. Browser PKCE/session/CSRF/logout
has controlled HTTPS acceptance; explicitly selected mock/demo login supports
ongoing development while production identity remains fail-closed. Existing
receiver/runtime attachment is required; machine/cloud provisioning is optional.
Aggregate cgroup integration has fake/offline validation only: this container's
read-only cgroup mount supplies **no real aggregate enforcement acceptance**.
Linux is selected; target runtime/delegation, non-toy scientific acceptance and
target-machine acceptance remain open. Older continuation summaries below are
historical and do not certify current integration or its exact-head CI.

The table below preserves the earlier PR9–PR14 review stack; it is not a list
of all current continuations. Current workflow status is in the scope note above
and linked audit; exact-head CI remains with each stage PR. This index separates
that historical tested runtime from later work under review. Every PR remains Draft. No merge, branch-history rewrite or deployment
has occurred as part of the delivery cleanup.

## Historical exact review order (PR9–PR14 stack)

| Order | Draft PR | Exact base → runtime head | Scope |
|---|---|---|---|
| 1 | [PR9](https://github.com/Guanzhw/agent-factory/pull/9) | main → `6793a96c21be88f7145efc55a1312a06ab787628` | Native material-driven Factory and governed remote execution |
| 2 | [PR10](https://github.com/Guanzhw/agent-factory/pull/10) | `6793a96c21be88f7145efc55a1312a06ab787628` → `4e1f29900080ad6004fd33f55580b9fe5ea75c37` | ORX/ledger, governance and bounded inference recovery |
| 3 | [PR14 checkpoint bridge](https://github.com/Guanzhw/agent-factory/pull/14) | `4e1f29900080ad6004fd33f55580b9fe5ea75c37` → `12c82a469e1172654ac7d57fc02ceeffb8db0bbf` | Exactly 1 commit, 31 files, +2548/-58; preserved AT10/Go WIP, not standalone acceptance |
| 4 | [PR11](https://github.com/Guanzhw/agent-factory/pull/11) | `12c82a469e1172654ac7d57fc02ceeffb8db0bbf` → `c374293bd93ec4759f235a340ca264978d9747b3` | Responsive authority checks, accounting/parser hardening and integration |
| 5 | [PR12](https://github.com/Guanzhw/agent-factory/pull/12) | `c374293bd93ec4759f235a340ca264978d9747b3` → `37f889e5cc157206868c60c00230bd3b8aef23a5` | Receiver-parent recovery within the original business deadline |
| 6 | [PR13](https://github.com/Guanzhw/agent-factory/pull/13) | `37f889e5cc157206868c60c00230bd3b8aef23a5` → current coordinator head; verified runtime `68b3dc78f4df75c791a9c32a9794ba00957f57e6` | Explicit Go fixture product path; subsequent delivery documentation and narrow bridge-review correction |

The checkpoint bridge was absent from PR10 and PR11's displayed diffs. PR14 now
makes it independently reviewable using the existing exact base/head branches;
no other branch was changed. Preserve this dependency during eventual authorized
integration. If a future squash/rebase changes ancestry, recheck downstream diffs
and resulting CI rather than assuming the recorded hashes still apply.

## Evidence, not a claim that every intermediate checkpoint passed

At runtime `68b3dc7`, push run
[37078502857](https://github.com/Guanzhw/agent-factory/actions/runs/37078502857)
and PR run
[37078542513](https://github.com/Guanzhw/agent-factory/actions/runs/37078542513)
each passed five jobs. Both PostgreSQL suites ran 618 tests with 63 explicit skips
(970.898s / 1147.419s). Fresh terminal observations were 89.154583s apart. Seven
actual local HTTP/PostgreSQL Go product cases passed; live Go requests were zero.
These are evidence for that exact runtime, not the standalone `12c82a4` WIP.

Opening PR14 automatically triggered a new historical full-suite run
`37080853771`; it was cancelled deliberately to avoid a redundant historical
rerun. Cancellation is not a pass. The bridge's own handoff retains its original
incomplete acceptance and receiver-parent failure. The independent review below
addresses its code directly; later passing CI does not replace that review.

## Independent checkpoint review

Reviewer scope: all 31 files in `4e1f299..12c82a4`, focusing on permissions,
original-run recovery, accounting and credential boundaries. No real credentials
or live provider were accessed, and no heavy test was launched by the reviewer.

- Recovery checks bind the original approval, parked native requirement, original
  task/run/plan, DONE result and positive stop evidence. Separate repair slots and
  dispatch CAS prevent an old approval receipt from silently executing again.
  Native continuation uses only the original queue ticket; no detached fallback.
- The checkpoint's Go parser admitted ambiguous/early/repeated stream usage and
  duplicate tool identities. Subsequent `ca12534` hardening rejects these cases.
  Missing usage still allowed output in the checkpoint; `68b3dc7` stops it and
  prevents queue replay from resetting the retry allowance. The bridge alone
  must not be deployed or described as having these later fixes.
- A remaining completed-log parent-directory check/open race was identified in
  `orx_local.read_completed_logs`. The coordinator correction pins each directory
  with no-follow directory descriptors and opens the final bounded regular file
  relative to its pinned parent; hardlinks are rejected. Deterministic race tests
  and existing recovery contracts validate the change. This correction is on the
  current coordinator branch, not rewritten into the historical checkpoint.
- The checkpoint browser helper installed its short-lived fixture header across
  the whole browser context. The coordinator correction injects it only through
  an exact-origin route fetch with redirects disabled; cross-origin requests are
  aborted, and service workers cannot bypass routing. Actual Chromium with two
  controlled HTTP origins verified three same-origin requests and zero requests
  to the cross-origin redirect destination. All values were synthetic. This is
  fixture credential isolation, not a production identity implementation.

No production IdP, research provider or scientific use case was selected.

Final correction review and focused check outcomes are recorded on PR13/PR14.
Validation: **41 focused tests passed**, including six parent-directory race
subcases; actual Chromium routing passed (three same-origin requests, zero
cross-origin redirect requests). Ruff/Pyright passed, and local Markdown path
checks plus `git diff --check` passed. Independent final correction review found
no blockers. Focused scope: completed-log directory/leaf races and hardlinks, platform capability
refusal, browser exact-origin routing, existing inference wait and approved-repair
contracts; Ruff/Pyright and local Markdown-link/diff checks. The current update
deliberately does not schedule another full suite for this bounded correction
and documentation cleanup; the commit uses the CI skip directive, and skipped
CI must not be reported as successful new-head CI.
No full-suite run is required solely for README or index changes. Any runtime
correction is explicitly distinguished from the earlier exact-SHA CI evidence.

## Current product boundary

Use [README](../README.md#current-acceptance-and-remaining-work) and the
[current matrix](ACCEPTANCE.md#current-matrix), not historical pending notes.
Default AutoResearch remains synthetic; the separately selected pinned local
baseline now has [real training and independent evaluation acceptance](RESEARCH_BASELINE_ACCEPTANCE.md).
Later host PubMed retrieval and governed Go coding results are recorded in the
current matrix; older zero-source/UNKNOWN attempts remain unchanged. Production
identity and scientific-provider/domain acceptance, real candidate comparison,
separate-host receiver/enforcement and department capacity/operations remain open.
Existing receiver attachment is required and implemented; machine provisioning
is optional, not a new mandatory gap.

## Bounded Go continuation

Branch `coord/go-bounded-live-validation-20261003` starts exactly at PR13 head
`d760b8af63c6692d0119c5386d7a7481076f61bc`. The predecessor's later full CI run
37081501616 passed all five jobs, observed twice 90.069s apart. This continuation
adds durable live admission and separate offline native-product tests; actual
live result is UNKNOWN after one DeepSeek smoke slot, zero Luna attempts.
See [bounded validation](GO_LIVE_VALIDATION.md). Final exact CI is maintained in
the new draft PR, with no merge or deployment.


## Offline safe-diagnostics continuation

Branch `coord/go-safe-diagnostics-20261003` starts at PR15 head
`45eeb6b88046a40f8743e01e69d10353be386499`. PR15 push 37103072210 and PR run
37103111700 passed all ten jobs; each PG suite ran 650 tests with 63 skips. Root's
two terminal observations were 106.515 seconds apart. The following diagnostics
stage is offline only: [scope, model-selection correction and boundaries](GO_SAFE_DIAGNOSTICS.md).
No historical evidence is overwritten and no second real request is sent. Final
new-head CI belongs to its draft PR, not to the preceding commit's results.

## Historical continuation summaries (superseded status)

The following text is retained as a record of the earlier stages, not the current
implementation status or required baseline.

Latest continuation: [existing remote runtime/process integration and isolation capability](REMOTE_PROCESS_ISOLATION.md)
reuses Factory handoff, effective receiver bindings and receiver-owned shared-pool
process custody. Strict root process evidence reaches the origin without remapping
custody IDs. The current environment lacks unprivileged aggregate delegation;
aggregate requests are explicitly unsupported, and a real enforcement backend
remains code work. Separate local service processes/real HTTP do not imply separate
physical hosts or production deployment. Older stage text below is historical.

Latest continuation: [native process and shared-lease integration](PROCESS_LEASE_RUNTIME.md)
connects original governed native task/run/plan identity to bounded cooperative
process custody, shared-pool holds, stop-only lifecycle reconciliation and a
Chinese owner-only lease view. UNKNOWN remains held; matching positive stop proof
alone permits release, independently of execution success. Aggregate isolation,
remote provisioning, production scientific contracts and target-host acceptance
remain open. Older stage statements below are historical; final exact-head CI is
recorded on this continuation's draft PR.

Latest continuation: [browser authentication and bounded process enforcement](BROWSER_AUTH_PROCESS_ENFORCEMENT.md)
implements code/PKCE/state/nonce, revocable browser sessions, CSRF/logout and Chinese
login UX, verified with a synthetic HTTPS IdP on desktop/mobile. A separate trusted
cooperative Linux adapter actually enforces per-process CPU/address-space/file-size
and process-group wall limits. Production IdP/TLS, aggregate isolation, lease/runtime
integration and target-host capacity remain open. Older stage statements below are
historical; final exact-head CI belongs to this continuation's draft PR.

Current resource/identity continuation: [implementation and acceptance](RESOURCE_IDENTITY_INTEGRATION.md)
adds shared compute admission, actual task-owned workspace allocation, stop-only
maintenance and a production-mode pinned access-token bridge. Production identity
configuration, browser login/session flows, remote provisioning and kernel quotas
remain distinct. The preceding PR24 record below is historical stage evidence.
Final exact-head CI is recorded on this continuation's draft PR.

Current continuation (2026-10-04): [Draft PR24](https://github.com/Guanzhw/agent-factory/pull/24)
adds explicit Luna revision2 and governed public literature contracts on PR23 exact
`a5173379ce7f119fdcf3540239fd82cb19ff86ab`. Live Luna coding completed with two
SETTLED attempts/4332 tokens/zero holds. Native host PubMed retrieved two actual
abstract-only sources; a separately labelled controlled synthesis used these real
sources without calling a scientific provider. The old failed container retrieval
and all UNKNOWN attempts remain unchanged. See [stage evidence](LUNA_SCIENTIFIC_CONTRACTS.md)
and [v0.3 scope reconciliation](V03_SCOPE_RECONCILIATION.md). Exact final CI belongs
to PR24; earlier green runs do not certify its head. No full-product, production,
scientific-validity, invoice or target-host acceptance is claimed.
Older status/gate statements below describe their original stage.
