# 验证记录

## 阶段一

基线97adbc8，集成#98 5799403、#97 965350f（后者fast40112590106成功，full40112603820仍待终态）。root串行运行重型检查。

- composition-two-apps：真实PostgreSQL/ASGI/Agno双应用、两种安装顺序2项通过，14.253s测试/17.628s driver，零skip。安装期间inert、原任务/取消/占用隔离与positive stop释放均验证；worker在运行期间补充model构造计数断言，不能外推新增计数也已执行，需后续固定源码复验。非TCP/live验收。
- composition-shutdown-assembly：原#98真实关闭/非零退出/重启原身份及原装配5项通过，108.716s测试/130.681s driver。process证据见scratch/task-history-20261024/composition-shutdown-evidence。没有延长35s生产期限或原fixture界限。
- 独立审查发现第二app启动失败时首app清理先于guard启动。现已在组合stack unwind之前调用幂等begin_shutdown并发布同一期限；实际短子进程同步阻塞清理exit1，保留原Timer35s参数，fixture仅加速真实timer。同步constructor/shutdown/abort契约禁止async callable静默漏await。
- composition-core-research-pure：131项，129通过/2失败/零skip（3.858s）。失败暴露新多owner取消实现扩大至外层workflow顺序，破坏旧不确定cleanup必须先传播的契约。已恢复该生产顺序，保留两个旧断言；新owner之间仍全部通知后传播。首次定向33项有1个新fixture仍要求旧候选错误顺序，记录保留，修正其预期为原外层契约后再验证。
- 首次静态失败569 missingimports源于新worktree没有独立venv；offline uv sync缺editables缓存，获准frozen安装锁定68包后重试，发现真实1项旧staticmethod override冲突。改为instance wrapper并让纯helper测试直接调用ResearchControlHooks，不忽略类型错误。最新静态结果另录。

证据目录/workspace/scratch/task-history-20261024，各label有command、UTC、exitCode与log。所有输入合成/loopback，无paid/live模型。阶段二graph全局桥接仍未迁移，不能声明#99完成。

最终stage1 Pyright零错误/警告，Ruff通过、架构739modules零violations/coverage gaps。取消顺序修正后33项通过（24.319s，runner27.161s）；旧131中的其余129已有通过记录，未机械重复所有131。新step1.5额外model计数还需固定源码复验，原验收语义已有两真实case通过。独立审查未发现新的确定阻断；全然丢失声明的未知历史binding不能自动识别为缺owner，声明缺席owner则保持UNKNOWN/held，此限制保留。

## 阶段二：显式实例graph（2026-10-24）

ResearchApplicationAssembly拥有ResearchServices，构造参数和ResearchFactory传递。删除全局_services/services_for/release_services。重复使用原settings/registration会重新绑定当前实例；原生第三方普通factory保持原契约，任意外部自定义closure不保证可自动重绑定。关闭/错Store/未安装graph拒绝调用。

root串行实际验收（均exit0，零skip）：
- composition-graph-fast：253 daily Python通过，39.299s（driver46.953s）。stage1 exactfast40113849544的两项旧Mock store fixture错误已保留并修复为真实空registry，不放宽生产分支。
- composition-graph-instances：4项真实PG/ASGI/Agno，42.063s（46.946s）。包含两安装顺序、新model构造断言、同进程双服务器复用registration/settings，关闭A后B原任务继续与原A factory拒绝。
- composition-graph-remaining-pure：82通过，1.402s（3.709s）。worker默认sandbox异步runner清理挂起记录保留；root实际授权环境运行原断言通过，没有修改超时。
- composition-graph-shutdown：5项真实进程与装配通过，101.263s（104.987s），原35s期限/非零退出/持久UNKNOWN/重启原身份保留。进程证据composition-graph-shutdown-evidence。
- composition-graph-scientific：原远程三阶段科研1项通过，418.204s（424.891s）。原receipt/共享预算/native身份实际运行，不是新简化fixture。
- 独立review发现5处脚本构造缺research参数，全部修正；AST复扫317生产文件/25相关调用无遗漏。随后composition-graph-baselines原2项PG通过32.146s（36.509s），验证实际candidate baseline与execute训练/评估/receipt脚本路径。
- composition-graph-static-final：Pyright零错误/警告。第二轮独立只读review未发现新增阻断，确认无隐藏Store locator、graph在app/observer/native清理后release。

上列PG输出仍含旧guardian Popen ResourceWarning；本分支未包含#103后续guardian修复，不能宣称清理警告消失或历史MCP偶发已根治。只验证确定性公开/合成与loopback，不代表真实供应商验收。其余最终检查另录，不把阶段结果当full CI成功。

最终本地门禁：独立core wheel实际安装/PG启动/cleanShutdown通过17.111s；npm run check exit0，707项通过/0skip，lint/typecheck/build完成70.025s；production/full npm audit各0 vulnerabilities，exit0。最终Ruff通过，architecture739 modules/0 violations/0 gaps。OpenSpec strict通过。新增daily ownership selection的原17项通过0.035s，collection验证full3318、dailyPython270、PG59，无重复lane；已有daily253加这17，无需重复整套。一个误用host Python运行check_python.py --help的检查实际进入collection且缺Agno/SQLAlchemy，未运行用例；该脚本没有help模式。随后仅通过锁定venv的inventory接口验证选择，不把host失败记为产品测试结果。最终full CI尚未运行。

## 精确1d2bbb7 full Windows fixture失败

fast40116000844成功，full40116074034仍在PG阶段；Windowsjob120937537734已失败3318tests，1failure/9error events、1247skip、285.497s。raw `/workspace/scratch/cloud-delivery-20261024/composition-1d2bbb7-windows.log`。错误来自遗漏的旧Mock应用registry、旧static timingwrapper、baseline context state缺graph、runtime构造和AutoResearchService测试子类缺research参数。

六个fixture文件已迁移：使用真实ApplicationRuntimeRegistry和ResearchApplicationHooks，read_wait spy证明实际app观察；graph显式传递；timing诊断fixture保留实例self绑定，实际class(instance,...)/bound-call验证四次成功/领域拒绝事件。原断言不降级。五模块19项通过0.222s，默认sandbox异步Runner阻塞后仅终止本任务PID，授权环境同命令通过。未改生产期限/断言或运行第二份full。

已merge #97 88aacb7，保留双方任务板历史；新增late-authority test改为显式ResearchServices，无重引入global locator。root composition-merged-fixtures六模块22通过2.655s（8.537driver），composition-merged-types零错误/警告22.412s。适配原始实例调用计时包装，未改取消/UNKNOWN断言。旧1d2bbb7 full仍独立保存，不把新fast或targeted成功改写成旧full成功。

### Original full CI terminal and remaining fixture migrations

Original exact1d2bbb7 full run40116074034 completed **failed**: PostgreSQL3318 tests/2690.485s, failures3/errors12/skips66; four required groups fully passed and three had a missing passing case. Windows failure remains recorded above. This is not accepted full validation, and no full rerun was requested to chase green.

Current7d0701f already contained six old-constructor/mock migrations and #97 terminal/reconcile barriers that explain the previously identified failures. The remaining PG-only fixture gaps were: evaluation service missing its explicit research graph; workspace fixture had not retained its state; preparation constructor mock omitted its graph. These three fixtures now use the same explicit graph as the application; no production code, assertions or timeouts changed. Preparation4pure tests passed0.087s; actual two original PG failure IDs passed in45.357s driver. All original auth/rotation/wrong-database and unavailable-workload no-dispatch checks remain.

Raw full log: `/workspace/scratch/cloud-delivery-20261024/composition-1d2bbb7-full-pg.log`; targeted evidence: `/workspace/scratch/task-history-20261024/composition-final-pg-fixture-migrations.{json,log}`. Exact7d0701f fast40118071375 succeeded; the new fixture-only head will receive its own fast checks. No whole-suite success is inferred from those results.
