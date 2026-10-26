# Design

## Context

动机及基线见 proposal。`DelegatedOperations._observe:105–111` 已从验证原 ticket/session 的 observer 取 child 正文，再把它放入原 journal 的 `output.result`。`workflow_contracts._inert` 递归禁止换行、URL、普通键名和 >4096 字符；输出整体 16 KiB／observation 32 KiB 的限制又覆盖正文，因而合法结果无法提交停止事实。

现有真实消费者：`WorkflowControl._external:189–194` 将原 observation 作为原 wait 的 tool result；`ResearchRounds.results:317–329` 返回该 observation，`context:256–269` 将前轮 observation 交给后轮。`ResearchEvidence.capture:68–70` 仅依赖 output.taskId/runId 并另读原 CLI receipt；SSH evidence 另走 `ApplicationRuns.delegated_child/ssh_results`。不能只把 result 改成未经消费的引用。

## Goals / Non-Goals

**Goals:** 正常结果完整持久化并到达已有消费者，停止与结果限额分工明确，修后能恢复原暂停 operation。

**Non-Goals:** 不改所有适配器的黑名单，不加正文索引、内容服务、artifact 写入、journal、任务调度或审批；不改 Research 源码和动态 native pin；不处理本次其他审计项。

## Decisions

### 1. 固定委派 envelope 内分别验证 metadata/result

仅精确 `native-delegated-operations-v1`、revision `1` 的 COMPLETED output 使用固定 `{taskId, runId, result, artifacts}` 形状。共享常量放在无运行时依赖的既有合同模块，避免合同反向导入适配器；原 adapter pin 的值不变。

`result` 为 JSON 数据：string/object/array/number/bool/null，object 键为字符串，数值有限；不做执行字段、URL或可打印字符过滤。一个小型共用编码/尺寸函数被 producer 和持久化合同复用，UTF-8 JSON 使用 `ensure_ascii=False`、固定紧凑分隔符、`allow_nan=False`；保存仍为 deepcopy 原值，不归一化或截断内容。

去掉 result 后的 output metadata 仍调用原 `_inert` 和 16 KiB 上限；外层 observation 去掉 result 后仍用原结构/32 KiB 上限。正文独立使用既有 application schema 最大输出预算 1 MiB 作为持久化读取的绝对上限，producer 使用具体 child plan 的 `budget.outputBytes`（既有 1024..1048576 范围）。不可再将完整 observation 套回 32 KiB，否则同一 bug 会换阈值重现。UTF-8 数据限额不是 ASCII 转义后的存储字符数；原 SQL JSON 序列化可能更长，但其膨胀有界。

原非委派合同完全保留；同名 result 出现在别的 adapter output 不获得例外。固定 envelope 不允许额外控制键；task/run/artifact 引用继续走原验证，预算以原 child plan 决定，不能来自正文。

### 2. 结果失败只在正向停止之后分类

`_observe` 继续先核对子树 allStopped 和原 failed/cancelled 分支。仅原 child 子树成功停止时才检查正文：预算内完整输出为 COMPLETED；超过 child 输出预算为 FAILED／`DELEGATED_RESULT_LIMIT`，不可编码数据为 FAILED／`DELEGATED_RESULT_INVALID`，均使用既有 FailureJSON 和 allStopped=true，output=None。异常捕获仅围绕正文转换，不吞掉 owner/child/stop/DB 读取错误。

这不是把未知工作强制结算：原停止证明先成立；新错误只是明确结果合同失败。原 native content 不改写，用户仍可沿现有原 native task/run 读取口检查它；不把失败结果自动发布为成功成果。既有 `_accept`、effect_complete、observer completion 与预算 settle 承担闭合，无新状态。

### 3. 保留现有 inline 形状，避免未接通引用和额外恢复依赖

选择独立 inline 数据合同，所有消费者的 `output.result` 语义保持相同；新增正常大正文与业务键不需要应用侧解引用。原 journal 本来就保存 child 正文，本改动没有再复制一份。

考虑过原 native 内容引用：它需要同时接通异步 wait 和事务内同步 Research 读取，并处理 native 历史清理后仍可读的问题；若改 rounds.py 还会改变 Research 动态 component pin。为修当前错误不新增这条跨层依赖。artifact 方案又需要原子、幂等归档和额外容量交接，当前没有必要。

## Risks / Trade-offs

- [放宽到任意控制字段] → exact adapter/revision 和固定 output 形状；只对 result 数据例外，原其他合同反例继续失败。
- [把小的固定上限换成新的完成死锁] → producer 使用原 task 输出预算，超限在已停止之后明确 FAILED 并闭合；容量边界/超界一字节均回归，不靠原样重试。
- [结果丢失或消费链断开] → custody 读写等值、原 wait 后续模型收到全文、本轮/前轮 Research 读取等值；真实 native fixture 使用含换行/URL且 >16 KiB 的正文。
- [读旧记录时新限额误杀] → 旧合同允许的结果小于新绝对容量；shape保持既有 producer 形状。旧 closed 不改写，原 open 由同 pin 正常 lookup/inspect 完成。
- [误称集成成功] → 先保留便携失败回归；PostgreSQL 时隙由 coordinator 串行批准，实际运行前不得把 native continuation／预算闭合写成通过。

## Migration Plan

无表迁移、无新 adapter pin、无历史数据回填。先非作者方案审查，再提交失败回归和最小实现，最后完整精确 diff 独立审查。回滚旧版本将重新不能读取含原合同不接受正文的已闭合 observation，因此不得将旧二进制直接接管这些新记录；回滚需保留本兼容读取修复或停止使用旧 reader，不删除结果来制造兼容。
