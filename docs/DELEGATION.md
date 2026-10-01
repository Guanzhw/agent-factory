# Bounded native delegation

`DelegationService` stores parent/child bindings around the single registered
`factory-executor`. Each child receives an immutable catalog plan, a distinct
factory task UUID/session, and its own native Agno durable queue ticket. Native
AgentOS and QueueWorker own execution, pause, continuation and cancellation. No
nested agent run, custom loop, second queue or additional executor is introduced.

## Integration

Construct `DelegationService(settings, store, auth, bridge)`, call `initialize()`,
then assign `store.delegation`. Metadata tables are `af_delegation_roots`,
`af_delegation_links` and `af_delegation_tool_calls`; native queue tables remain
owned by Agno. The service uses the existing Store admission, immutable plan,
capacity, effects and event interfaces and the public NativeBridge lifecycle.

| Method | Contract |
| --- | --- |
| `await create(owner, parentTaskId, goal, mode, requestId)` | Returns `childTask`, native `receipt` or null, persisted `link`, and `duplicate`. |
| `await children(owner, parentid)` | Direct children and factual native/effect state. |
| `await inspect_group(owner, parentid)` | Parent and all descendants; `pending`, `unknown`, `allStopped`. |
| `await cascade_cancel(owner, parentid)` | Persists cancellation for the subtree, requests every nonterminal acknowledged native cancellation, and returns current facts. |
| `authorize_child(run_context)` | Synchronous current ancestor authority guard at every protected child operation. |
| `consume_tool_budget(run_context, call_id, name)` | Atomically charges a native execution ID once against the root and each ancestor subtree. |
| `has_pending_children(task_id)` | Conservative synchronous capacity guard: unresolved admission, native state or effects retain the parent reservation. |
| `delegation_scope(owner, parentTaskId)` | Current owner-only UI permission, pinned scope and durable aggregate budget facts. |
| `application_group_status(parent_status, group)` | Derives application state without changing native ticket status. |

Wire `authorize_child` into Store tool authorization. Wire `consume_tool_budget`
into native Function execution using its actual call ID, including standalone
root tools before the first delegation. The native per-run tool limit remains
in place; the persisted aggregate limit also prevents children multiplying it.
Use public `Function.pre_hook(run_context: RunContext, fc)` and `fc.call_id`.
On denial, raise `StopAgentRun`: Agno 3.1 tool pre-hooks propagate its
`AgentRunException` base. `InputCheckError` stops native Agent pre-hooks, but is
swallowed by Function pre-hooks and cannot enforce a tool execution boundary.
Use `has_pending_children` before marking a native-completed parent's capacity
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

Depth is at most two edges below the root. A root can create at most four
descendants over its lifetime, including unresolved intents; ancestor budgets
may lower those limits. Active descendants consume the existing global and
per-user Store quota. The production default remains two active tasks per user;
hierarchy tests explicitly raise this to eight. Root and descendants share the
root plan's total tool execution budget, and every intermediate ancestor also
limits its own subtree. Charges persist across restarts; reusing the same native
call ID does not charge again, while changing its tool conflicts. This free
synthetic runtime makes no claim about paid token/cost accounting.

A PostgreSQL root advisory lock serializes creation, budget charging and cascade
intent. The lock covers committed metadata phases and is released before native
HTTP. A persisted, fingerprinted intent precedes Store reservation; the child
binding is committed before native submission. Goal whitespace is normalized.
Matching requests reuse the immutable child; changed semantic requests conflict.
A crash between phases may leave an intent or receiptless task. Retrying recovers
metadata and performs exact native receipt lookup only. It never submits that
reservation again and never releases uncertainty by elapsed time. UNKNOWN
effects likewise remain UNKNOWN. No side effect is replayed by delegation.
An effect reservation while native computation is known running is shown as in
flight; it still retains capacity. Unresolved effects become externally UNKNOWN
when native execution stops without confirmed result or cleanup evidence.

## Cancellation and group outcome

Cancellation acceptance is a request, not proof of process termination. Every
owned descendant gets the durable cancellation flag before native transport.
Native terminal tickets need no extra cancellation request. Running synthetic
experiments observe their own durable flag, stop their owned child/process group,
and settle the effect only after verified cleanup. An uncertain admission or
UNKNOWN effect keeps `allStopped` false even if other native tickets are terminal.

A completed native parent with an active child is `waiting_children` in the
application view. Any group uncertainty becomes `unknown`. When all children
are known terminal, child failure produces `failed` and child cancellation
produces `canceled`; otherwise the parent's completed state can stand. A canceled
parent with pending descendants remains `canceling`. The native statuses and
effect facts remain available unchanged in each snapshot. A fully observed,
stopped root group is marked reclaimed and cannot acquire a new mandate.

Already accepted active children may finish after their parent completed, while
fresh children from a completed parent are denied. Failed/rejected/canceled
ancestors and current revocation deny protected child operations. Automatic
observation of spontaneous parent failure and background cancellation of every
child is not implemented here. An operator/API reconciliation can inspect facts
and call cascade cancellation; this limitation must not be advertised as an
autonomous failure cleanup guarantee.

## Verification

Use a disposable loopback PostgreSQL database with Agno exactly 3.1.0. Set
`FACTORY_TEST_DATABASE_URL` and run from `platform`:

```powershell
python -m unittest discover -s tests -p test_delegation_postgres.py -v
```

The opt-in tests exercise actual native QueueWorker tickets, owner isolation,
mode/capability subsets, depth and lifetime root counts, native Store quotas,
immutable snapshots, restart metadata, current revocation, aggregate budget
deduplication/exhaustion, paused-tree cancellation, running experiment cleanup,
completed-parent waiting, and controlled unknown transport/effect retention.
An execution-level aggregate budget test resumes a root after its child consumed
budget and proves the denied native tool creates no artifact. Child-plan reuse
is rejected without adding a factory task or native queue ticket. Each class
creates its own generated loopback database and disposes its engines before
dropping only that database; UNKNOWN outcomes are never released for test cleanup.
Only model responses are synthetic. Literature fixtures are invented and labeled;
these tests make no claim of successful real research or paid-model verification.
