# Current delivery and review index

This index separates the latest tested runtime from the historical stack under
review. Every PR remains Draft. No merge, branch-history rewrite or deployment
has occurred as part of the delivery cleanup.

## Exact review order

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
Default AutoResearch is synthetic; measured PubMed retrieval returned zero
sources. Production browser identity, a specific research provider, non-toy
workload contracts and a real compute allocator still need implementation and
real configuration/acceptance. Default Go subscription preflight stays blocked; the explicitly attested bounded
validation campaign stopped after its first UNKNOWN smoke attempt. See
[separate live evidence](GO_LIVE_VALIDATION.md).


## Bounded Go continuation

Branch `coord/go-bounded-live-validation-20261003` starts exactly at PR13 head
`d760b8af63c6692d0119c5386d7a7481076f61bc`. The predecessor's later full CI run
37081501616 passed all five jobs, observed twice 90.069s apart. This continuation
adds durable live admission and separate offline native-product tests; actual
live result is UNKNOWN after one DeepSeek smoke slot, zero Luna attempts.
See [bounded validation](GO_LIVE_VALIDATION.md). Final exact CI is maintained in
the new draft PR, with no merge or deployment.
