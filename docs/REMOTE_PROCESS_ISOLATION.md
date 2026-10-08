# Existing remote runtime / process lease integration

Continuation of [Draft PR27](https://github.com/Guanzhw/agent-factory/pull/27),
exact base `2e66b50fdd3ef27ca8b36b2f27b39a287d7df8eb`.
Branch `coord/remote-process-isolation-20261004`. Final exact-head CI is recorded
on this stage's draft PR. No deployment, merge or host security change is implied.

## Reused contracts and the actual gap

| Existing component | Responsibility retained |
|---|---|
| `TrustedHandoffClient` / `PreparedHandoffService` | One durable origin placement, receiver preparation/review, one dispatch, original receipt reconciliation; no second native submission through `resources.attach`. |
| `RemoteBindingService` | Exact source material/manifest pins, receiver-local effective adapter configuration, mapped owner and versioned proof. |
| `OriginAuthorityTransport` | Current source authority over authenticated HTTP; cancellation, denial and unavailable authority remain distinct. |
| Receiver native Agno queue | Sole native ticket and receiver-owned execution; origin holds metadata and usage admission, not a fabricated local native run. |
| `ProcessRuntimeService` / `ProcessResourceProvider` | Receiver-local immutable task/run/lease/process identity, shared ComputePool admission, positive stop/reclaim and UNKNOWN retention. |
| Lifecycle/delegation and handoff receipts | Process holds contribute to group stop evidence and origin task/usage release. |

The missing junction was source-versus-effective target validation. A source
`origin-process` binding may legitimately map to `receiver-process`, but the
process service previously compared the receiver tool against the immutable source
configuration. It now resolves the existing verified effective manifest under the
original receiver native context. The source plan and hash are never rewritten.
The HTTP authority wire vocabulary now recognizes the bounded process tool; the
selected server contract, plan guards and current grants still determine authority.

A handoff for the selected process contract now includes strict `processLeases`
evidence. It is a complete snapshot for the **receiver root task**, containing at
most one original lease. Owner, task, native run, plan, lease fingerprint, provider
job, binding, pool identity and reservation limits must match. Previously observed
lease identity cannot disappear or be replaced. Only matching positive stop proof
allows RECLAIMED; failure/limit outcomes remain distinct from capacity release.
The origin refuses `allStopped` while receiver process capacity is held. No
parallel process transport, universal resource proxy or optional A2A path was added.

The Chinese remote-task view presents the receiver's actual identifiers and pool
reservation, without rewriting them into origin custody IDs. It has no allocation,
cancel or reclaim buttons. Root-only evidence does not claim coverage of every
remote descendant; existing group stop semantics continue to cover task trees.

## Isolation capability and enforcement boundary

`isolation_capabilities()` returns a bounded read-only report. The cooperative
backend supports per-process CPU time/address space, per-file size and cooperative
original-group wall deadlines. `required_isolation` is operator configuration on
the process provider. Unsupported/unknown requirements fail before directory or
allocation effects; admission and final dispatch recheck facilities. Existing
original-custody cancellation/reclaim do not reapply a new admission requirement.
Resource discovery reports these capabilities; presence of a socket, namespace or
controller never upgrades a backend to verified aggregate enforcement.

The actual task environment exposes cgroup v2 controllers, but its cgroup mount is
read-only and its delegation files are not writable. There is no observed user
systemd bus. The enclosing four-CPU/16-GiB ceiling is shared environment capacity,
not a task quota. A read-only metadata query reached a Docker daemon, but it was not evidenced
as rootless/task-owned authorization; no container was created. No cgroup,
namespace, mount, daemon, host network or security setting was changed.

**Aggregate enforcement is unsupported and not implemented by this stage.** This
is a real remaining backend gap, not merely a missing credential. A future backend
needs an operator-provided delegated subtree (or an independently reviewed runtime
with equivalent task-owned authority), controller enablement, child-group creation
and attach/readback permission, pinned original group identity and positive whole-
group termination evidence. CPU/memory/pids control does not by itself provide
aggregate disk/IO quota, network isolation or a hostile-code sandbox. Kernel
[delegation requirements](https://docs.kernel.org/admin-guide/cgroup-v2.html#delegation)
are distinct from observing the enclosing host's limits.

## Acceptance and scope

Tests use two separately owned local service processes, independent disposable
PostgreSQL databases and real loopback HTTP. The receiver starts real fixed
cooperative processes. Models, identities and keys are temporary controlled
fixtures; keys are kept only in temporary owner-readable configuration and never
committed. Child environments exclude provider credentials. This proves process
and transport boundaries on **one physical host**, not separate machines, remote
TLS, a deployed IdP or target-host capacity.

The first governed end-to-end case passed in 32.528s: separate approvals and exact
source/effective mapping, one receiver native ticket/lease/process, no origin
native ticket or compute lease, owner-only downloadable receipt and verified
artifact hash/provenance. The initial ten-case serial matrix passed eight cases;
two deadline-sensitive assertions required causal diagnosis. Final focused expiry
and disconnect cases passed together in 57.397s with the original deadlines.
Expiry accepts only positively stopped unsuccessful outcomes: actual lease-expiry
cancellation or a proved guardian limit. The read-disconnect test records the real
503 response boundary before expiry with zero cancellation; any later cancellation
must identify the original expired lease and actual send time. The strengthened
UNKNOWN/restart case also passed: both origin and receiver task/disk/capacity holds
remain, and the shared pool rejects an unrelated owner with 429. Full exact-head CI
runs the complete matrix again; its final results belong to the draft PR.

Actual browser acceptance passed in 69.678s using independent normal and UNKNOWN
fixtures, each with real origin/receiver services and PostgreSQL. Desktop 1440px
and mobile 390px screenshots were inspected. Both cases preserved receiver IDs,
with zero browser writes, extra launches, page errors or horizontal overflow;
unrelated-owner access was denied. Normal execution was COMPLETED/exit 0/RECLAIMED;
UNKNOWN retained capacity. Frontend 106 tests/build and dependency audit passed;
Ruff and Linux/Windows Pyright reported no errors. Independent review passed 34
light checks; final causal-test and browser evidence review found no blocker.
Local full Python validation passed1058 tests (717pass/341skip) in53.654s;
PostgreSQL is disabled for that local full pass and is exercised by the separate
real-service cases and the full CI PostgreSQL job. [Sanitized evidence](evidence/remote-process-isolation-2026-10-04.json)
keeps the initial failures distinct from the causal corrections. Initial exact CI exposed two Windows fixture path assumptions despite clean
Windows static checks. The simulated Linux mount probe now uses POSIX path
semantics and the constructor fixture uses a native absolute program path. All
assertions remain; no production code or platform skip changed. Ten focused checks
and independent review passed; replacement exact-head CI revalidates Windows.
Mock tests alone are not live enforcement.

## Remaining implementation and deployment inputs

- Aggregate backend and independently tested aggregate resource enforcement remain
  code work. The new report and refusal path do not close that requirement.
- Remote machine/environment provisioning remains code work; this integration
  attaches work to an already configured Factory receiver.
- Production scientific-provider accounting/retry/pricing integration and non-toy
  dataset/evaluator/candidate-approval workflows remain code work and real-science
  acceptance. Coding subscriptions are not silently used as research providers.
- Cross-host TLS/identity/owner-mapping, monitoring/recovery and measured 32-core/
  64-GiB or 54-core/192-GiB capacity remain real-environment acceptance.

Useful inputs for that later acceptance are the intended existing receiver URL
and Agno/Factory revision, the non-secret issuer/audience/subject-to-owner mapping,
the selected target-host profile, and whether an already delegated cgroup subtree
or approved rootless runtime exists. Supply credentials through the established
secure environment only, not in plans, material definitions, repository or chat.
This stage needs no new credential, paid resource or host permission to complete
its independently testable remote work.
