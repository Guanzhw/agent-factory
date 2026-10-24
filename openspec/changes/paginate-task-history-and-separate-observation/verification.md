# 验证记录

环境：已有云端 `/workspace/agent-factory-history`，4 CPU / 16 GiB，Python 3.12.14、uv 0.12.1、Node 24.19.0、npm 11.9.0；锁定Agno 3.1.0。基线main `9a933aa8aadda1b80b216cf67f399974690c6fc6`，保留原规划branch并合入main。临时PG17.11仅监听127.0.0.1，测试各自创建/删除随机DB；重型运行串行。无真实模型/外部账号调用。

## 同夹具局部比较

固定scratch `task_history_baseline.py`，真实PG与HTTP，205条记录含1条真实native执行及204条合成历史rejected记录；不代表205次执行。两次都读取100条，fixture observer暂停。

| 指标 | 原实现 | 本实现 |
| --- | ---: | ---: |
| 请求窗口store-engine SQL | 4268 | 1 |
| native detail调用 | 2 | 0 |
| 响应bytes | 336856 | 34977 |
| 单次请求秒 | 4.349300 | 0.076313 |

只说明本夹具读路径的工作减少；非统计压测，不推断整套或目标机性能。SQL计数不包括独立native engine的权限审计。

## 已运行

所有下列通过命令exit0，无跳过；完整原始日志与命令JSON在durable `/workspace/scratch/task-history-20261024/`。

| 检查 | 结果/证据label |
| --- | --- |
| `unittest test_task_history_postgres` | 4通过；205个相同时间戳完整分页、owner/cursor隔离、限额、摘要不释放容量 |
| 本地分页+usage ledger+科研summary | 28通过，`history-local-ledger-pg` |
| 科研只读投影+既有receiver+status矩阵 | 42通过，`history-scientific-read` |
| 远程completion/cancel/lostACK/禁用origin后台收尾 | 4项实际通过；首轮另1项GET fixture失败，未忽略 |
| PREPARED撤权fence、dispatch CAS先胜不可误证stop | 2项实际通过；同轮GET隔离仍失败 |
| 无执行锁读取、真实并发settlement一致快照、GET生命周期隔离 | 3通过，`history-snapshot-pg` |
| 独立远端阻塞/单flight/取消join/真实5s观察预算 | 3通过，reviewer scratch记录 |
| daily fast Python | 220通过，39.588s，`history-fast-python` |
| `npm run check` | lint/typecheck/705 tests/build通过，`history-web-check-fixed` |
| 官方registry full与production audit | 均0漏洞 |
| built Chromium历史场景 | 255任务/跨poll新增105，Enter/Space、真实back、区域503独立刷新通过；全外部请求拒绝，`browser/results.json` |

最终daily PG、静态/架构、独立core与精确CI另行补记录；不以worker交付代替这些结果。

## 失败与修正依据

新remote测试首次导入错误：实际函数被误放main guard之后，修正TestCase归属与实际discovery。随后GET监听最初混入native worker写，停止两端observer/scheduler/worker后仍捕获真实权限审计与event cursor元数据；保留这些既有行为，仅对精确SQL允许例外，不预热隐藏它们。扩充锁捕获后发现ledger.inspect仍取执行全局锁，改为REPEATABLE READ READ ONLY快照，并用真实并发settlement和持锁fixture证明非阻塞及一致性。首次events读取保留专用schema lock及stream CREATE/INSERT，不能宣称所有GET零写/零锁。

首次Web check exit2为两个旧fixture仍返回数组；按新Page契约修正，保留原断言，随后完整705通过。所有失败log保留。

## 审查与限制

独立审查发现并修复：禁用origin的后台原操作收尾、远程网络等待阻塞本地observer、头页跨50项新增形成永久分页缺口。公共权限不放宽；若receiver凭据本身失效/receiver身份被禁用，无法取得可信远端停止证明时仍保留UNKNOWN和hold。

科研GET使用已验证持久claims/custody，不能据此宣称live供应商或冷启动缺失driver已恢复；需要恢复driver的操作仍由显式/后台reconciliation承担。审计PR103的本地完整偶发失败尚未归因，本分支不宣称关闭。此PR保持Draft，不合并或部署。


## Daily PG失败保留

`history-fast-pg`：58项，56通过/2失败/0跳过，284.137s unittest（295.088s driver），exit1。失败为MCP `test_http_authentication_rejection_releases_capacity_without_tool_dispatch` 与 `test_slow_delete_releases_predispatch_failure_after_local_cleanup`，均在prove_released的第二个成功任务未在20秒内达到native terminal；原容量释放/首次失败回执已先通过。尚未归因，不能判作历史失败而忽略，也不重复整组追绿。正在针对排队/授权/两次调用/清理阶段诊断。

独立复核发现legacy local计划的_commitment会在READ ONLY读取中写migration；已增加persist=False纯计算路径，真实落库仍仅执行路径，验证待补。不得因现代计划snapshot测试通过就忽略旧计划。

Legacy pure-read修复后targeted3项PG通过/0跳过（1.660s），覆盖未迁移local计划及祖先、非local仍拒绝新增花费、实际显式迁移保留原plan bytes。

最终Ruff、Python架构边界（0 violations/0 coverage gaps）及OpenSpec strict均exit0。

## 第二任务关联诊断（保留失败）

`mcp-original-prefix-diagnostic`按daily原顺序运行前12项一次，11通过/1失败/0跳过，159.339s测试、168.305s driver，exit1；没有并发重型测试。第二任务b0d5ee84-87c4-4c0b-97a5-da819f8fcca4、native run ece44983-cc70-4361-b9bf-0f62300a42f2：工具两次均返回；native于20秒界限内约19.964s完成，随后容量terminal等待失败。不是原20秒失败的精确复现。

相对trace秒：DELETE凭据callback180于151.286297开始，153.148364原2秒期限取消；最终授权callback182于153.859503完成；原凭据callback180直到154.387933才返回。取消跳过其lease类型/原身份及尾部授权校验，因此182不能覆盖迟到结果，UNKNOWN目前正确，不得清flag或重派发。所有callback均已开始且最终完成，不是PR103修复的未开始callback事件遗留。

callback180有189条SQL，wall3.101637s、thread CPU0.652443s、SQL wall2.336546s；pool等待总1.328ms。两个不同backend SELECT同时约1.1s，两个loop lag约1.05s；44个PG样本无blocker，主要ClientRead。进程CPU、配额throttle有增加，但不足以唯一归因CPU/GIL/宿主争用。首次两case诊断还出现原任务wait_terminal失败，另保留mcp-second-run-analysis.txt；不能称稳定性已解决。

原始安全trace、分析、命令和退出码位于scratch的mcp-original-prefix-*、mcp-second-run-*；无凭据/SQL参数输出。独立审查认为应先定位重复授权工作，只能在完整证据下考虑有界原回调收尾，禁止简单延长超时或清除实际拒绝。

独立核心wheel安装/实际loopback启动/干净关闭/临时DB清理通过（history-core-install，12.303s，exit0）。最终Pyright零错误零警告。Web架构首次漏传必需--config，exit2，仅命令配置错误；正确配置另录。

正确配置Web架构检查exit0（history-web-architecture-configured）。daily PG未通过且共同原因仍在诊断，保持Draft验收限制，不将局部读路径收益外推整体稳定性。

## 精确CI与兼容夹具修正

head4be4eb4的fast CI40101761285全部success。full CI40101802533的Windows discovery在3231项中5 errors/1238 skips；5项均由旧夹具未适配新内部接口触发：nominal定价fixture transaction不接受read_only（2项）、remote receipt mock不接受persist=False、科研observer facts缺unknown、stopproof断言依赖最后一条SQL。原日志保留history-full-windows-errors.log。

修正仅测试夹具：SQLite实际query_only并断言只读/no lock；remote显式persist=False且原row不变；观察facts补全并保持取消不写失败事件；stopproof定位terminal更新并补summary不得释放/重开终态。原语义断言保留。定向15项通过/0跳过（0.071s），Ruff通过；未改生产或放宽期限。完整PG仍等待该次run终态，后续修正head需重新验收。

## Full c123 findings and targeted corrections

Exact full run 40103188592 completed with failure: 3232 cases, 29 failure events, 15 error events, 66 skips, 2309.121s; error events include repeated teardown errors and cannot simply be subtracted as unique failed cases. Windows and other jobs passed. Old 40101802533 was cancelled, not accepted. Raw failure tracebacks are retained in cloud scratch `task-history-20261024/history-c123-failures.txt`; original evidence is not replaced by targeted passes.

The new page response broke two remaining array-consuming fixtures; HTTP cleanup then leaked active tasks and produced subsequent 429s. Migrated full page traversal and original cleanup checks: seven actual PG/process cases passed. Separately, read-only details exposed native completion before durable finalization, so immediate retention/source/admission operations correctly remained blocked. Added display-only `finalizing`, with pending cancellation remaining `canceling`, shared by detail/history. UNKNOWN and failure precedence and stop proof are unchanged. A real native task with observer held proves both reads retain the original row; restarting only the observer settles without GET/reconcile. Nine boundary/state cases passed; original capacity/storage 15 and synthesis/cancellation six passed with original assertions. Web707 and dailyPython220 passed, Pyright zero errors. No production timeout extension.

Remote accounting tests now distinguish observed completion from explicit accounting actions, with an origin-only background observation gate proving GET keeps original ledger/grant/placement unchanged. Four targeted real-process cases passed before finalizing integration; final combined verification remains tracked separately. Default sandbox dailyPython stalled in async mock cleanup and was interrupted after91.985s with stack retained; same single mock case passed in the approved execution environment, then dailyPython220 passed. No live provider or paid call.

Final combined remote-usage module: nine actual process/PG cases passed, zero skips, 163.207s unittest / 165.442s driver (`history-remote-usage-finalization`, exit0). Independent review checked pure scientific reads, original-identity validation before cleanup POST, and locked receipt CAS. Scientific unit regressions39 passed; three additional cleanup-receipt tests use the actual receipt validator and reject five forged variants before any POST. Ruff and Pyright passed.

The original three-phase scientific test still failed after splitting controller reconciliation from history reads (`history-scientific-control-split`, 65.070s unittest / 69.336s driver, exit1). This time preparation reached COMPLETED and its retained claim exists, but receiver reconciliation returned409 before training. The original900s deadline was not reached. Response/body and receiver traceback diagnostics were added to identify the exact validation boundary; no blanket retry or relaxed identity check was introduced. This remains an acceptance blocker, not a passing synthetic/live claim.

The instrumented original case (`history-scientific-receiver-diagnostic`) failed after451.968s /457.643s driver, reaching evaluation. Receiver tracebacks now identify `RETENTION_BUSY` in checkpoint identity and evaluation verification: the single retention-fence connection is already held by concurrent evidence observation. The captured wording maps to the fast-failing pool acquisition, not proof of an advisory-lock collision on the same object. Original fences remain intact. An exact-busy historical-evidence projection is under implementation; all other409/identity/authority failures must continue propagating. This new evidence does not retroactively establish the uninstrumented65s error's exact source.

Residual original regressions: five of six passed (`history-residual-failure-regressions`,132.975s); the remaining command-response assertion still expected immediate canceled rather than canceling. It now accepts only the two legitimate acknowledgement states, then waits for canceled and retains the original positive stop/terminal/ticket assertions. That case plus forwarded-question/local-child/artifact case13 passed (`history-final-remote-state-cases`,2cases/77.319s/zero skips). Storage crash recovery,20-user bounded pressure and source/synthesis/comparison all passed in the five-case result. Daily Python with new selectors passed231/zero skips,36.117s; architecture723modules/zero violations/zero gaps and OpenSpec strict passed. No original timeout increased.

The exact-busy projection is now implemented at only preparation/checkpoint identity and evaluation verification. It rechecks the original binding, retains the already observed lease, discards this round's partial claims, and marks retained claims as historical. No claim means no scientific completion. Other conflicts, corruption and revoked authority still fail. New deterministic contention cases plus existing receiver cases38 passed/zero skips (`history-contention-unit`); independent review found no new bypass. Pyright passed. The original three-phase PG test is running under unchanged assertions/deadline; this paragraph is not an end-to-end acceptance claim.

Further original-case results remain failures: `history-scientific-contention-fixed`521.756s/529.230s driver reached all three completed phases but controller called `start_phase` again after the original child became terminal. It also exposed an evaluation whose successful claims were still absent when origin finalized. Controller now checks the validated existing drive intent and only observes it; successful scientific stop requires the corresponding verified phase claim, while cancellation/failure retains the original physical-stop path. Seven real-validator claim cases and18 controller cases passed, including no redispatch after terminal intent, missing claims, retained claims, and held lease rejection.

`history-scientific-finalization-gate`193.064s/210.735s driver failed at `USAGE_REMOTE_STATEMENT_STOP`: an observation captured unfinished native/group facts before awaited evidence verification, then obtained a concurrently CLOSED ledger statement. Added a single bounded refresh of the same original receipt when this exact contradiction occurs. If fresh stop proof still disagrees, reject before origin persistence; accounting never substitutes for stop proof. Origin also rejects late observations that would regress already confirmed stop. Six deterministic receiver/origin interleaving tests passed; original read-only disconnect cases passed alongside. Ledger doubles are explicitly synthetic, not PG evidence. The original case is now running as `history-scientific-coherent-receipt`; no full-suite repeat or relaxed assertion/deadline has been used.


Final targeted integration: `history-scientific-coherent-receipt` passed the original complete three-phase process/PG case, zero skips, 485.217s unittest /489.750s driver. Original identities, shared budget, dispatch counts, assertions and deadline remain intact. The three most affected usage/origin-interruption regressions then passed, zero skips, 68.030s unittest /70.964s driver (`history-coherence-usage-regressions`). This is one passing scientific run after preserved failures, not proof that all historical MCP timing failures are resolved.

Latest receipt interleaving/disconnect checks: seven passed/zero skips; Ruff, Pyright (zero errors/warnings) and OpenSpec strict passed. Final fast Python collection validates253 selected cases (not an execution claim); earlier231 execution and each newly selected targeted test are recorded separately. Independent review found no new identity, stop-proof or accounting bypass; persistent contention can still conservatively reject rather than fabricate completion. Exact final-head CI is pending publication. All fixtures are synthetic/local; no paid or live external model was called.

## 精确965350f full失败与定向收敛（2026-10-24）

full40112603820（PGjob120927320891）终态失败：3265项，3195通过、4失败、66skip，2531.997s；5/7required groups通过，owner_byok与autoresearch各1未通过。Windows/Web/browser/static通过。raw `/workspace/scratch/cloud-delivery-20261024/history-965350f-full-pg.log`。

前三项失败为native/receiver结束早于origin持久收尾：legacy BYOK read得到finalizing；restoredmember handoff17 origin terminal仍false；usage08 origin statement.allStopped仍false。前两fixture改为原30/15sdeadline内读取Store等待后台terminal，保留原GET和身份/效果断言。第三项按既有usage01契约显式POST reconcile原回执再断言origin ledger；它不是后台自动收敛证明。`history-full-barrier-fixes` 3项通过（59.341s driver），没有延长期限或修改生产超时。

第四项科学失败trace为project_evidence初次authorize成功后，并发observer结束原source evaluation child，随后evaluation.verify再次请求执行授权被拒；晚到拒绝与初次就已拒绝的历史读取路径行为不一致。原日志有完整三phase已完成、retained evaluation claims和精确receiverReceiptTracebacks，不归为timeout或无害flaky。

修复仅处理两种精确晚到origin拒绝（直接409/真实transport403），重新授权仍须拒绝，再只读核对原binding/native/正向已释放lease与完整retained claims。仍授权、身份变化、缺claims、held custody或其他evaluator异常保持原失败。不证明source正常完成、当前credential或artifact保留期仍有效，不新读artifact、不执行、不写journal；与初次custody_only历史证据语义保持一致。独立review无具体阻断；真实凭据轮换/保留期到期未由新mock单元测试覆盖。

新增Event确定性交错3项含两error形态及负例；combined16纯测试通过。原`history-late-authority-scientific`实际三阶段通过572.256s（driver576.205s）。旧guardian ResourceWarnings保留。不是全部full通过，也不能关闭历史MCP第二任务等待问题。未重新启动整套追绿；后续以修复提交的fastCI和本定向证据报告。
