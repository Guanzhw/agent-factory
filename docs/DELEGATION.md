# Native delegation

`DelegationService` stores parent/child bindings around registered native Agents and Workflows. Each child receives an immutable catalog plan, a distinct
factory task UUID/session, and its own native Agno durable queue ticket. Native
AgentOS and QueueWorker own execution, pause, continuation and cancellation. No
nested agent run, custom loop, second queue or additional executor is introduced.

## Integration

Construct `DelegationService(settings, store, auth, bridge)`, call `initialize()`,
then assign `store.delegation`. Metadata tables are `af_delegation_roots`,
`af_delegation_links` and `af_delegation_tool_calls`; native queue tables remain
owned by Agno. The service uses the existing Store admission, immutable plan,
lifecycle, effects and event interfaces and the public NativeBridge lifecycle.

| Method | Contract |
| --- | --- |
| `await create(owner, parentTaskId, goal, mode, requestId)` | Returns `childTask`, native `receipt` or null, persisted `link`, and `duplicate`. |
| `await children(owner, parentid)` | Direct children and factual native/effect state. |
| `await inspect_group(owner, parentid)` | Parent and all descendants; `pending`, `unknown`, `allStopped`. |
| `await cascade_cancel(owner, parentid)` | Persists cancellation for the subtree, requests every nonterminal acknowledged native cancellation, and returns current facts. |
| `authorize_child(run_context)` | Synchronous current ancestor authority guard at every protected child operation. |
| `consume_tool_budget(run_context, call_id, name)` | Records a native execution ID once for the root and ancestor subtrees; does not enforce a quota. |
| `has_pending_children(task_id)` | Conservative completion guard: unresolved admission, native state or effects keep the parent nonterminal. |
| `delegation_scope(owner, parentTaskId)` | Current owner-only UI permission, pinned scope and durable tool/child counts. |
| `application_group_status(parent_status, group)` | Derives application state without changing native ticket status. |

Wire `authorize_child` into Store tool authorization. Wire `consume_tool_budget`
into native Function execution using its actual call ID, including standalone
root tools before the first delegation. There is no aggregate or per-run tool-call quota. Persisted call identities
prevent duplicate accounting and reject reuse for a different tool.
Use public `Function.pre_hook(run_context: RunContext, fc)` and `fc.call_id`.
On denial, raise `StopAgentRun`: Agno 3.1 tool pre-hooks propagate its
`AgentRunException` base. `InputCheckError` stops native Agent pre-hooks, but is
swallowed by Function pre-hooks and cannot enforce a tool execution boundary.
Use `has_pending_children` before marking a native-completed parent
terminal. Parent cancellation must call `cascade_cancel`, including a parent
whose own native run has already completed. Apply `application_group_status` to
the application view after collecting `inspect_group` facts.

## Scope and durable admission

Fresh children require an accepted queued, running or paused parent ticket and
CURRENT native owner rights and execution policy. The parent, root and every
ancestor must retain their immutable mandate, ownership and cancellation scope.
Child tools and capabilities must be subsets of every ancestor. Tools still
come from the existing registered allowlist. Child mode cannot add experiment
authority absent from a literature parent's plan.
Delegated plans cannot enter the ordinary instance admission route. Every child
operation independently requires its immutable parent/root/depth binding to
match persisted links; a reused child plan with an ordinary request ID is denied.

Delegation has no project depth, cumulative descendant or tool-call quota.
Store admission has no per-user or global active-task quota. Historical numeric
budget fields remain in immutable plans; they no longer block these operations.
Preview reports effective shared limits as `null`, with actual usage counts.
A repeated native call ID remains idempotent; reusing it for another tool conflicts.
This accounting is not paid token or cost tracking.

Agno's configured worker concurrency still governs simultaneous execution.
Queued work waits for a worker. A research Agent can use `research_wait_child`
to pause its native run and release that worker while its child executes.
This uses native continuation, not a second scheduler.

The comparison reference is [Codex at 0ed34eb9](https://github.com/openai/codex/blob/0ed34eb9ceddc759e283f0d657be9339afc6b25a/codex-rs/core/src/config/mod.rs).
Its V1 and V2 limits have different meanings. V2's four concurrent session
threads include the root; that is neither four lifetime descendants nor Agno's
process-wide worker count. Factory does not invent a per-session scheduler to
claim equivalence. Ownership, exact parent bindings, cycle detection and user
cancellation remain valid independently of numeric quotas.

A PostgreSQL root advisory lock serializes creation, call recording and cascade
intent. The lock covers committed metadata phases and is released before native
HTTP. A persisted, fingerprinted intent precedes Store reservation; the child
binding is committed before native submission. Goal whitespace is normalized.
Matching requests reuse the immutable child; changed semantic requests conflict.
A crash between phases may leave an intent or receiptless task. Retrying recovers
metadata and performs exact native receipt lookup only. It never submits that
reservation again and never releases uncertainty by elapsed time. UNKNOWN
effects likewise remain UNKNOWN. No side effect is replayed by delegation.
An effect reservation while native computation is known running is shown as in
flight; it still prevents premature finalization. Unresolved effects become externally UNKNOWN
when native execution stops without confirmed result or cleanup evidence.

## Cancellation and group outcome

Cancellation acceptance is a request, not proof of process termination. Every
owned descendant gets the durable cancellation flag before native transport.
Native terminal tickets need no extra cancellation request. Running synthetic
experiments observe their own durable flag, stop their owned child/process group,
and settle the effect only after verified cleanup. An uncertain admission or
UNKNOWN effect keeps `allStopped` false even if other native tickets are terminal.

A completed native parent with an active child is `waiting_children` in the
application view. An acknowledged running parent remains `running` while a
child admission is pending; that child retains its uncertainty facts. Once the
parent stops, unresolved group uncertainty becomes `unknown`. When all children
are known terminal, child failure produces `failed` and child cancellation
produces `canceled`; otherwise the parent's completed state can stand. A canceled
parent with pending descendants remains `canceling`. The native statuses and
effect facts remain available unchanged in each snapshot. A fully observed,
stopped root group is marked reclaimed and cannot acquire a new mandate.

Already accepted active children may finish after their parent completed, while
fresh children from a completed parent are denied. Failed/rejected/canceled
ancestors and current revocation deny protected child operations. The delegation service exposes inspection and cascade cancellation; it does
not own a background polling loop. In the assembled application,
`FactoryLifecycleObserver` observes parent failure and authority loss and
requests cleanup of the original task tree. [Lifecycle observation](LIFECYCLE.md)
describes that integration and its single-process limits. A cancellation request
still requires positive native and effect evidence before the group is stopped.

## Verification

Use a disposable loopback PostgreSQL database with Agno exactly 3.1.0. Set
`FACTORY_TEST_DATABASE_URL` and run from `platform`:

```powershell
python -m unittest discover -s tests -p test_delegation_postgres.py -v
```

The opt-in tests exercise actual native QueueWorker tickets, owner isolation,
mode/capability subsets, immutable snapshots, restart metadata, current
revocation, repeated-call accounting, paused-tree cancellation, running process
cleanup, completed-parent waiting, and unknown transport/effect retention.
They create descendants beyond the former depth and count limits and verify
that lifecycle observation still finalizes the stopped group. Historical numeric
tool budgets do not prevent the root from completing after its child has run.
Child-plan reuse is rejected without adding a factory task or native queue ticket.

The current 15-case delegation suite passed against disposable PostgreSQL and
Agno 3.1.0. Each class creates its own generated database and disposes its engines
before dropping only that database. UNKNOWN outcomes are not rewritten as
success or released by a timeout for test cleanup. Model responses and research
inputs are synthetic; this is native execution verification, not a real-model
research or complete Windows platform acceptance result.
