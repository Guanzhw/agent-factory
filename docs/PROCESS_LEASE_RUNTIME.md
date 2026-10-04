# Native bounded-process / shared-lease integration

Continuation of [Draft PR26](https://github.com/Guanzhw/agent-factory/pull/26),
exact base `ce0c06f21ced442344f46b36587297f2518100e9`.
Branch: `coord/process-lease-runtime-20261004`. This stage connects the existing
Linux process adapter to governed native execution and shared resource leases.
Final exact-head CI and review observations are recorded on the new draft PR.

## Execution and custody

An operator explicitly registers `process_runtime_profile.registrations` and a
`ProcessResourceProvider` with a pinned executable/arguments, finite limits,
private custody directory, owner scope and `ComputePool`. The tool takes no
model-selected command or target. The governed plan binds one approved target;
`bounded-process-v1` uses the existing `compute:local` permission. The supplied
`process_settings` and publisher are labelled controlled fixtures, not a default
production or scientific application.

`af_process_runs` binds the immutable plan hash, native task/run, owner, request,
target and original lease. Its insertion and resource reservation share one
PostgreSQL transaction; a task row lock serializes reservation against both
lifecycle completion and opportunistic admission cleanup. The unique task/effect
binding is retained after reclaim. Native retries can inspect the original work;
they cannot create a replacement allocation, including after successful release.

`af_process_allocations` records durable intent before creating the original
journal or dispatching. Exact lease, plan, target/pool/provider configuration and
journal identities must match on reopen. A late cancellation/authorization fence
runs after blocking database checks and before dispatch. Missing launch replies,
missing journals, mismatched configuration and unknown dispatch remain held.
They are never repaired by relaunching the task.

Linux custody uses boot ID, PID birth/start time, original group, pinned journal
and directory identity, and a bound positive stop receipt. A guardian tracks the
original cooperative process group. Missing guardian proof, PID reuse, changed
boot or tampered identity cannot authorize signalling a replacement or releasing
capacity. This is for trusted task-owned cooperative workloads under the same
UID, not a hostile-code security boundary.

## Reconciliation and visible outcomes

The existing lifecycle observer scans bounded original process bindings even
after native task completion. Cancellation, current authority revocation and
lease expiry trigger original-custody stop-only cleanup. It neither creates an
admin execution identity nor restores a revoked grant. Database unavailability
and ambiguous identity remain UNKNOWN. Cancel/release transmission is claimed
durably once; lost replies are reconciled through inspection, never retransmitted
as a new operation.

Only a matching positive original-process stop proof permits release. UNKNOWN
retains shared CPU/memory/disk/slot reservations and task/storage capacity.
`executionStatus` and `exitCode` survive reclaim: FAILED and LIMIT_STOPPED do not
become success because their capacity was released. Successful native tools write
an owner-scoped process receipt artifact with exact original identities and
`researchValidated: false`. Failed terminal work also records its stop receipt
before reporting a tool failure. Receipt deduplication uses a separate session
lock connection, so full fresh authorization does not deadlock a size-one metadata
pool.

The Chinese resources panel reads a bounded owner-only lease projection. It shows
execution outcome, stop proof and held/released capacity separately, including
UNKNOWN and failure. It exposes no executable arguments, journal paths, PIDs,
credentials or process-control buttons. Browser viewing cannot start another
allocation. This stage uses the existing demo session for UI evidence; PR26's
synthetic HTTPS OIDC/session evidence remains a separate test.

## Validation

Local acceptance and exact CI are completed by the coordinator after worker
handback. The checked-in tests cover actual PostgreSQL/native/OS identity,
shared-pool contention, current cancel/revoke, process deadlines, lost launch/stop
replies, restart, uncertain dispatch, atomic terminal/admission ordering and
concurrent receipt deduplication with a size-one pool. Mock tests independently
exercise delayed dispatch authorization and outcome preservation. Browser
acceptance uses a real native success and a separately labelled controlled Popen
failure; no lease-response or browser route mocks are used.

Initial final PG run: 8 of 9 passed; the remaining assertion incorrectly required
an exception when a completed context read its original receipt. That expectation
was corrected to accept the same immutable receipt while requiring zero launches
and exactly one original allocation. No replay implementation was added.

The first default suite exposed 18 failing subcases in one legacy observer mock:
its unrestricted Mock synthesized a process service and incorrectly reported a
held lease for every task. The fixture now explicitly declares no process service;
a separate regression verifies that a genuine UNKNOWN process prevents group
release. This correction preserves the original terminal-race assertions.

Actual Chromium browser acceptance passed at 1440px desktop and 390px mobile:
one normal native process completed/released; a second controlled Popen failure
stayed UNKNOWN/held. Zero page errors, browser mutation requests, horizontal
overflow or cross-owner visibility; exactly two allocations, neither browser-created.
The four screenshots were inspected. Stopped-but-held is covered by unit tests,
not claimed as a browser scenario.

The strengthened actual UNKNOWN test passed in 13.207s: native execution reached
`cancelled`, but task and storage reservations remained held through both explicit
terminal observation and later admission cleanup. Exactly one allocation and one
launch attempt remained. Its initial expectation of native `failed` was corrected
to require an actual terminal state, without weakening the hold assertions.

Final default suite: **1028 total = 697 passed + 331 environment-gated skips**,
50.886s. Frontend98, actual process engine12, provider mock14, profile6 and strict
receipt8 passed; Ruff/Linux and Windows Pyright clean; npm audit zero known
vulnerabilities. Independent final checks38 passed. Exact CI runs the full
PostgreSQL suite separately; local skips are not counted as executed acceptance. See [machine-readable evidence](evidence/process-lease-runtime-2026-10-04.json). Exact push
and PR checks must both finish on the same committed head and be observed twice;
prior PR26 checks do not certify this code.

## Remaining product work and boundary

This closes the bounded cooperative process lease/native-task wiring, not all
v0.3 delivery. CPU/address-space limits apply per process and file-size limits per
file; the wall guardian covers a cooperative original group. Shared pool totals
are admission accounting, not aggregate kernel enforcement. Hostile children,
escaped sessions, total directory/disk use and network isolation are not certified.
If original identity or positive stop cannot be proved, the safe result is UNKNOWN
with capacity held; no administrative force-release is invented.

Remaining code includes a chosen production scientific provider's usage/retry/
pricing integration, non-toy dataset/evaluator/candidate-approval contracts,
remote machine/environment provisioning and an approved aggregate isolation
backend. Production IdP/TLS configuration, real scientific validation and measured
32-core/64-GiB or 54-core/192-GiB load/operations acceptance require their actual
environments and inputs. No Go key read/call, new credential, paid provisioning,
host/cgroup security change, merge or deployment occurred in this stage.
