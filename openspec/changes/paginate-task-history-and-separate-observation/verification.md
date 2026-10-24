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
