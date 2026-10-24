# Verification

## Complete serial comparison

Cloud checkout `/workspace/agent-factory-cloud-main`;4 CPU/16 GiB cgroup. Python3.12.14,uv0.12.1,Node24.19.0,npm11.9.0; frozen dependencies including Agno3.1.0/MCP2.3.0. Both runs use PostgreSQL17.11 CI digest, separate fresh volumes,2 CPU/1 GiB/pids256, loopback55432, fsync/synchronous_commit enabled. One heavy runner; source frozen within each run. Host caches not reset; no live provider.

Command for each: `uv run --no-sync python /workspace/scratch/suite-review-20261024/profile_suite.py --output /workspace/scratch/suite-review-20261024/{baseline,after}`, with disposable `FACTORY_TEST_DATABASE_URL`.

| Measurement | Exact code | Passed / failed / skipped | unittest seconds | Driver seconds / exit |
|---|---|---|---:|---|
| Before,10:12 UTC | `9a933aa8aadda1b80b216cf67f399974690c6fc6` |3131 /1 /66 (3198 total)|3555.380|3576.996 /1|
| After,11:39–12:43 UTC | `6f82b4abd2a3487dd756882766d3e313cb949fb9` |3139 /2 /66 (3207 total)|3807.505|3830.558 /1|

Both passed all seven required groups without skips:130/33/9/11/10/19/6 cases. **Neither complete run passed. Unittest/observer elapsed increased252.125s (complete driver increased253.562s); no suite-wide speedup or stability claim.** Same external observer SHA256 `f727282452ba52e345261bddf2b68bf9ff6bc601ef7681c82301e829d02a7688`; exact discovery IDs filter nested runner selftest events. Ten cheap regressions added, one remote case merged; counts are not the value metric.

The only subsequent code change is optional-profiler traceback formatting plus one deterministic regression, verified separately below; local complete comparison does not cover that later change. Exact final-commit CI must be recorded in the Draft PR and local delivery evidence.

## Cost and independent coverage

| Workload | Before seconds | After seconds | Decision |
|---|---:|---:|---|
| Remote scientific3 phases |275.05|306.74|Retain: original remote receipts and shared budget|
| Local scientific parent/children |117.77|131.12|Retain: distinct local custody/reconstruction|
| Entire remote process module |253.27|250.96|Retain distinct crash/revocation/UNKNOWN/deadline cases|
| MCP capacity module |130.02|172.43|Retain original second calls and UNKNOWN/restart paths; after includes failure|
| Remote handoff module |111.75|136.56|Retain scoped reads/HITL/child provenance; baseline includes failure|
| Governed remote module |108.11|125.87|Retain original-process authority boundaries|
| Remote usage module |101.17|124.12|Retain authoritative usage/uncertain acknowledgement boundaries|
| Remote completion + same-task replay |41.251|22.794|Merge replay into same completed-task journey;18.457s less observed work|
| Actual24204-file inventory case |84.221|41.705|Remove redundant repeated calls, preserve scale/corruption;42.516s less observed work|

The last two comparisons passed on both sides; observed combined reduction60.974s concerns those workloads only. A prior targeted four-case run also passed (remote23.718s,scale34.979s); it is not an independent statistical performance estimate. Unchanged cases varied substantially and failure outcomes changed.

Baseline case phases:setup844.30s,test2493.12s,teardown68.20s,cleanup70.98s.404 isolated-PG creations43.53s;25 process-server starts124.24s;11 containing pair starts117.20s overlap. Class fixtures are separate; helper spans must not be added to case totals. Async loop/executor closure is wall-only. Frozen observer has incomplete nested-run/subtest phase attribution and can truncate assertion traceback frames; original acceptance results/messages remain authoritative. The reusable profiler addresses these diagnostic issues separately.

Coverage mapping:

- `test_remote_process_runtime_postgres...test_02_completed_request_replay_preserves_released_process_identity` is merged into `test_01_governed_remote_process_original_identity_receipt_and_owner_isolation`. Every identity, single launch/allocation count, artifact/hash/provenance and owner404 assertion remains, using the same completed task. One two-database/two-process fixture removed, no mutable class fixture sharing.
- `test_research_inventory_scale...test_24204_files_observed_and_staged_without_truncation` retains24204 real files, count/tail, full capture and real driver success, then tail corruption refusal and unchanged config bytes. Four repeated observer/driver calls removed (not a claim of exactly four disk traversals). Existing small `test_research_local_driver` dynamic-ID replay now checks byte equality; pristine deletion detection remains in `test_research_package_paths`.
- Keep expensive delayed dispatch, lost cancel acknowledgement, origin/receiver revocation, native restart and20-user pressure because failures differ. Do not delete five SSH PG checks for only1.19s or broad model receipt coverage by count. Remote bindings setup35.79s/body.97s remains a future fixture candidate, without proof safe to share state.
- CI already runs full PG once and reuses its results for required groups. Windows remains a distinct platform. No workflow change or re-credit for PR96.

## Failures: confirmed repair versus unresolved observations

1. **Queued MCP callback custody defect confirmed and fixed.** Same deterministic five-case probe: original3fail/2pass, repaired5pass. Cancellation/submission failure before worker entry left a phantom unfinished callback; a shared start/abandon gate now prevents later entry and acknowledges never-started work. A callback already running retains custody until its actual finally. Tests preserve ContextVar, value/exception identity and dequeued-before-wrapper behavior. No production deadline changes.
2. **Historical MCP authorization-budget exhaustion remains unclassified.** Original takeover credential failure occurred in the second successful call (authRejected,36/36 callbacks); slow-delete failure had27/28 callbacks finished. Two-case trace passed:355SQL per DELETE across current-authority checks, callbacks.516–.645s. Recorded takeover commands had no overlapping heavy checks; only short GitHub reads/dry-run. No evidence to blame them, remove guards or claim latency fixed.
3. **After-run MCP DELETE405 failure is a different observed stage:** first failed operation released and restart completed; the new task failed to reach native queue terminal state within original20s. It did not reach the later capacity assertion, so historical auth timeout is not established. One original-case diagnostic passed25.500s/zero skips: all25/36/36 callbacks finished, no authorizationRejected, DELETE callback sums.655–.749s, observed loop maximum lag130ms/36ms. This successful diagnostic cannot explain the full failure or prove stability; no repeat-to-green.
4. **After-run ORX double-click case:** original `entered.wait(5)` returned false before the first POST gate. A suspected auto-release overlap bug is not the observed assertion and was not implemented as its fix. One original unchanged diagnostic passed: worker create.034s, gate reached, second resultack_unknown, first acknowledged, one POST. No swallowed production exception observed. Historical pre-POST delay/early failure remains unknown; original5s limits and assertions unchanged.
5. **Baseline remote handoff13:** original parent remained running after answer. Native heartbeat updates `locked_at`, so it does not establish claim time. Isolated original1case and ordered13-case prefix passed; full after also passed. Cause remains unresolved; original15s deadlines unchanged.
6. **Node environment restriction identified:** minimal node:test works, default sync-child probes returnEPERM; default architecture test9pass/1fail. Approved same binary standard10pass. Added spawn error/signal diagnostics, no fallback/skip/assertion weakening. Post-edit default negative probe explicitly reportsEPERM and approved10pass.
7. **Optional profiler traceback defect confirmed and fixed after measurement.** Wrappers lacking unittest's framework marker hid the actual assertion frame. Added `__unittest` marker and a regression checking actual user frame/source while required acceptance still rejects. Before6cases:5pass/1fail; after6pass. Frozen external observer was not changed retroactively.

## Other applicable validation

Exact argv,cwd,UTC,duration and exit code are in task-local `<label>.json`, raw output in matching `.log`:

- `targeted-mcp-profiler`:61pass/0skip; `mcp-capacity-after`:original6pass/0skip; `pruned-targeted-profile`:4pass/0skip. All exit0, earlier than complete after failures.
- `profiler-group-smoke`:original execution_invariants6pass/0skip; `profiler-traceback-before/after`:expected negative then6pass.
- Ruff; Pyright0errors/0warnings; Python/Web architecture; OpenSpec validation:exit0.
- `core-install`:real isolated core wheel/newvenv/emptycwd/-I, PG/native worker start, application absence and clean shutdown,acceptedtrue,exit0.
- `web-check`:60files/695tests,build/typecheck,exit0. Both npm audits0vulnerabilities. `browser-smoke`:two actual Chromium scenarios with synthetic APIs,exit0.
- `final-fast-python`:final231pass/0skip,32.671s,exit0; discovery3208.
- Pre-final collection3207 IDs:230fast Python/58fast PG/2919manual-only; collect-only is not execution. Later traceback regression adds one cheap Python case.
- Independent code review found no blocking callback/pruning issue; acceptance failures and traceback correction explicitly recorded. Public added-line credential-pattern scan is supplementary, not exhaustive.

## Evidence and boundaries

`/workspace/scratch/suite-review-20261024/`: `full-{baseline,after}.{json,log}`, `{baseline,after}/{summary,ranking,discovered-ids}.json`, timingsJSONL, `comparison.json`, `case-costs.csv`, environment snapshots, callback/Node/remote/MCP/ORX diagnostic records and `REPORT.md`. Earlier failures remain `/workspace/scratch/cloud-takeover-20261024/` unchanged. Full local runs were not repeated to obtain green.

Branch `chore/profile-test-cost-20261024`; original checkout/branches preserved. Both owned PG containers/volumes were removed after inventory showed only four foundation databases. Scoped process scan found no live owned fixture server;70 global zombie entries remain, without inferred ownership or a blanket clean-process claim. Publication/exact-CI status is recorded in delivery evidence/PR. No production or target-machine acceptance, real science/model/provider call, merge or deployment is claimed. Unresolved timing failures remain follow-up limitations; they are not excused as environment failures without evidence.


## 2026-10-24 后续共同MCP诊断与有界查询工作

原b458028的fast CI40095703648和full CI40095719568均success；full PG3208项=3142通过/66显式跳过，1372.371s。Windows、Web、Chromium与独立core亦通过。其终态不关闭本地两轮失败。

#97分支daily PG又出现HTTP auth rejection与slow DELETE两项第二任务20秒native等待失败（56通过/2失败/0跳过）；一次原daily前12项顺序诊断11通过/1失败，此次第二任务在约19.964秒native completed后，容量terminal等待失败，不能视作原20秒失败精确复现。task b0d5ee84-87c4-4c0b-97a5-da819f8fcca4、run ece44983-cc70-4361-b9bf-0f62300a42f2的两次工具均返回；DELETE credential回调151.286297开始，153.148364原2秒deadline取消，最终授权检查153.859503结束，原credential直到154.387933才返回。其lease类型/身份/尾部授权校验被取消，后者的成功无法替代，因此保留UNKNOWN正确。全部callback开始并结束，不是排队callback未开始的原缺陷。没有真实凭据拒绝证据，也不能据此清flag。

两个backend SELECT和两个事件循环约1秒同时停顿；采样未见DB blocker，pool获取仅毫秒级。CPU/throttle有增加，但不能唯一归因CPU/GIL/GC/宿主争用。安全trace和原身份在`/workspace/scratch/task-history-20261024/mcp-original-prefix-*`与`mcp-second-run-*`。

新增3项确定性loopback反例：迟到相同lease、漂移lease、resolver异常，均保持UNKNOWN/stoppedFalse，无重resolver/tools/DELETE；3通过。使用0.1秒配置与Event协调，不修改生产2秒期限。

静态调用图与受控SQL实测一致：authorize83 SQL、credential189 SQL。不能删重复guard：tool=None与具体name可有不同语义，bindings guard还可替换。改为每次require_materials_current对最多30个显式pins进行单LEFT JOIN，局部行仅本次检查使用；保留各pin完整性、runtime adapter、每root独立DFS及后续fresh检查。原实现本来没有撤回/dispatch原子锁；单statement改变本次检查中的撤回可见窗口，不能声称所有interleaving完全等价。撤回后的下一调用拒绝保留。

新增5个真实PG及1个DFS单元全部通过（4.822s，driver23.015s）；覆盖30pins单statement、fresh撤回、遗漏transitive、异sha重复pin、缺material404/治理409、immutable/bootstrap、深度、adapter drift及独立cycle路径。

计数实验首次测量与worker源码恢复交错，authority-cost-before的59/141实际对应中间双SELECT候选，已保留并排除。随后冻结worker，由root从Git恢复原file并在运行前后核对源hash，authority-cost-original-frozen为可信原版83/189；同冻结probe候选authority-cost-after为55/133，每次guard/helper调用数保持。原版case21.053s/driver24.569s，候选case22.370s/driver26.227s；**没有单例总耗时改善证据，更不声称整套加速或不稳定根因已解决**。测量顺序为候选后补受控原版，每种仅一次，非统计benchmark。可信比较为authority-cost-controlled-comparison.json；旧comparison.json保留但因首baseline无效不得引用。

既有材料治理+迟到回调+其余5容量case共30项通过/0跳过（107.666s，driver133.765s）；结合独立DELETE405实验，6类容量行为都实际通过。Ruff/Pyright零错误。

单次GC扩展原12case前缀全部通过（driver126.865s），不是原history分支前缀的严格性能对照。最大gen2在107.255312–108.673982持续1.418670s，回收95,253；slow_delete第二任务callback119覆盖107.122103–108.769686，wall1.647583s/threadCPU0.098949s、55SQL合计0.109270s/单SQLmax6.142ms；两loop同期lag1.326699/1.339067s。进程CPU同段增加1.55s、cgroup throttle零，支持本轮collector/GIL停顿，而非SQL或pool耗尽。最大gen0/1为24.102/54.821ms。本轮第二任务native11.127s完成；这建立一个明确暂停机制，但**没有证明历史失败都由GC造成**。未关闭GC、未延长deadline、未改变测试顺序/断言、未强制GC移动成本。报告`mcp-prefix-gc-analysis.txt`及原身份trace全部保留。

## Fixture生命周期与诊断保留（独立于生产判断）

无任务/工具派发的原fixture启动→stop→restart→doCleanups探针确认：第二代native/factory engine在client lifespan exit开始之前dispose，cleanup回调6→8。改为每generation独立ExitStack，client exit后再执行fixture engine dispose，stop立即清空该代回调；再次运行同探针，cleanup4→4且顺序正确。native lifespan自身仍有内部native DB close，不能把它算作fixture错误的提前处置。原store/engine仍可能因环和fixture属性存活，不宣称全部graph已立即回收。

纯顺序/partial startup/exit失败/手动reopened store/幂等5tests通过；真实native重开原回执+撤权及MCP slow DELETE两项通过（29.938s，driver41.524s）。未改原任务/调用/回执断言。

ObservedMCPAdapter仅在super.invoke完成收尾后的finally将state换成标量与Event tuple，避免测试诊断长期保留invocation→旧store graph；迟到callback自己的闭包仍持其实际custody，Event继续实时反映完成，UNKNOWN不会因此清除。新增weakref（无需GC）/late Event单元与fixture5项共6通过。外部scratch tracer仍强持state，可能延长graph寿命并改变GC扫描规模，不能把其1.419秒幅度直接外推历史无该tracer运行；未强制GC或调阈值。

原始顺序证据fixture-lifecycle-{before,after}.jsonl及对应命令log均保留。修复确定的fixture清理错误与诊断保留，不等于历史MCP/ORX/remote等待已全部修复。

最终daily Python241通过/0跳过（41.396s，driver45.802s），full discovery3223、daily PG59仅collection/选择确认，未重跑整组PG追绿。最终Ruff/Pyright零错误。

另一次轻量标量观察的单app最多6顺序任务，保持原20s/5s期限、零restart/零retry/零强制GC，实际6/6完成、12次原工具调用、每任务2个DONE completed effects、无authorizationRejected，所有临时服务正常清理；native等待至terminal区间8.368–9.315s。3次gen2最大190.184ms（gen0/1最大3.543/3.546ms）。driver61.612s。该probe绕过的仅fixture保留state诊断，不绕过生产MCP方法或monitor；原始身份/阶段/GC计数在mcp-single-app-six-events.jsonl和analysis.json。它支持单app该短窗口未重现，但不足以证明长期稳定，不能将与重启prefix的差异全部归于生命周期修复或强tracer。
