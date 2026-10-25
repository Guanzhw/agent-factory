# Passing replacement task: critical-path observations

Existing trace only; no tests, new instrumentation, or production edits. Scope: auth-rejection replacement task `1ca6ba36-946d-4e79-95ad-416913e427ed`, native `101a76cf-36e0-4a61-9961-d1095590738a`. Two successful MCP invocations take6.454693s and7.115846s. Claim→exit spans14.920711s; this is not the unrecorded native wait duration. Historical20s failures remain unexplained.

## Phase partition

Times below are relative to each invocation, in seconds; intervals partition wall time and may contain concurrent monitor callbacks.

| Phase | Invocation1 | Invocation2 |
|---|---|---|
|Initial credential validation, before `_run`|0–0.547819|0–0.617966|
|Transport/session context construction to `_call`|0.547819–0.549422|0.617966–0.619662|
|Initialize/discovery/pre-tool checks/tool/post-tool check in `_call`|0.549422–5.653739|0.619662–5.685165|
|Session teardown, including DELETE auth/transport, to `_run` exit|5.653739–6.287863|5.685165–6.923917|
|Final authorization + invocation cleanup|6.287863–6.454693|6.923917–7.115846|

Invocation1 HTTP transport method entries: POST1.417259, POST2.965681, GET3.013765, POST3.751270, POST5.409693, DELETE6.278083. Corresponding method enter→exit durations total0.067600s (individual6.15–19.36ms). Invocation2: POST1.446271, GET2.768701, POST2.903031, POST3.963241, POST5.521500, DELETE6.891014; total0.083868s (6.63–18.86ms). These timings end when transport returns response headers, NOT when response streams finish. Method-only tracing deliberately did not record JSON-RPC bodies; labeling every POST as a particular RPC would be inference, not direct evidence.

Concrete serial chains explain large gaps:
- Invocation1 initial checks callbacks10/11/12 authorize→credential→authorize finish0.547s. First request checks13/14/16 finish1.416s, immediately before first HTTP1.417s.
- Concurrent request checks18/20/23 and19/21/24 finish2.965s/3.013s, immediately before POST/GET. Callback24 contains the394.897ms cursor wall spike; no long GC overlaps it.
- Callbacks26/27/29 finish3.751s before next POST. Explicit pre-tool credential checks30/32/34 end4.617s; subsequent request checks35/37/38 end5.409s before last non-DELETE POST. Post-tool check40 ends5.653s.
- DELETE chain41/42/44 finishes6.277s, immediately before DELETE6.278s. Final check46 finishes6.454s.
- Invocation2 corresponding DELETE chain78/80/82 spans5.688–6.890s. Callback82 alone takes0.624497s (SQL0.472995s, ownCPU0.110686s), after credential80 finishes6.264s. DELETE enters6.891s; `_run` closes6.924s; final check83 completes7.115s.

Second DELETE preparation occupies about1.205s from `_call` exit to dispatch, within the production2s budget. The auth-flow deadline itself was not instrumented, so exact budget remaining cannot be stated. It is material cost, not a reproduced near-expiry failure.

## Work volume and overlap

Invocation1:29 authorize +8 credential callbacks,2659 successful SQL cursor executions. Invocation2:30 authorize +8 credential callbacks,2714 executions. Authorization normally55 statements, credential133. Callback-thread interval union clipped to invocation wall is6.394887s/7.050403s, respectively (~99%). This shows callback work is active across nearly all wall time; concurrent monitor work means it does not prove every covered nanosecond is blocking the critical path.

Summed callback thread CPU3.760068s/4.260050s; summed SQL cursor wall5.095883s/5.679626s. These overlap between callbacks and with each other: do not add them to obtain elapsed time, subtract them as exclusive phases, or equate cursor wall with PostgreSQL execution time. Eight credential resolutions generate16 surrounding authorize callbacks plus8 credential callbacks in `state.credential()` (24 total, not24 authorize). Each credential callback also includes two synchronous authority checks internally, already counted within its133 SQL statements. The remaining top-level authorize callbacks are explicit dispatch/post-tool/final checks and periodic monitor checks. GET/POST authorization can overlap, as the paired chains above show.

## Intentional fixture behavior versus runtime cost

The replacement resets `tool_schemas`, DELETE refusal/drip settings, and releases the DELETE event before submitting. Its `echo` tool immediately appends a scalar call record and returns; it contains no sleep. The native fixture requests two tool invocations, so their sequential total is intentional workload, not duplicate accidental execution. The0.25s authorization monitor interval is deliberate fixture configuration; its sleep is concurrent monitoring, not a serial minimum delay per HTTP request. The separate pure-readiness case's150ms credential sleep does not apply here. The first slow-delete operation's intentional blocked DELETE likewise does not apply to this replacement task.

Production `MCPToolAdapter` creates a fresh HTTP client/ClientSession per invocation; initializes, verifies discovered tool schema, explicitly validates credentials before tool dispatch, and supplies fresh `_OwnerAuth` checks for each outgoing method. `state.credential()` checks authority before and after credential resolution; `_call` and `invoke` perform additional post-result/final checks. Those implemented freshness boundaries explain repeated work across separate protocol phases. This trace does not establish they are interchangeable or safely removable. Previous fresh-query optimizations already reduced per-callback SQL; removing another check would need a separate proof preserving revocation, exact credential lease, schema and original invocation identity.

## Conclusion and limits

The passing critical path is dominated by repeated fresh authority/credential work between short local HTTP-header round trips, with concurrent monitor overhead. No intentional replacement-server sleep, repeated tool dispatch, leaked old owner, or accidental extra invocation is evidenced. No concrete redundant runtime operation or production bug is proven. A single395ms cursor-wall spike lacks backend attribution; total callback CPU/SQL cost is an observation, not the historical timeout cause. This does not justify caching authorization, weakening guards, changing timeouts, or another diagnostic rerun while the required union full CI runs.
