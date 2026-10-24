# Spec Delta

## Purpose

让成员在明确总预算和截止时间内执行可追踪的串行科研轮次，保留每轮原生任务、不可变基线与独立评价来源，并在回执丢失、重启和取消时恢复原操作而不分叉或重置额度。

## ADDED Requirements

### Requirement: Immutable activity and unique successor
系统 SHALL 持久化活动目标、owner、preset/模型/资源 pins、总 cap、绝对截止时间及轮次谱系。每轮 MUST 为独立原生 root，同一前轮至多有一个后继；后继意图与全轮预算预留 SHALL 原子提交。

#### Scenario: Concurrent continue
- **WHEN** 两个请求同时继续同一前轮
- **THEN** 返回同一原后继身份且只预留一次，内容冲突被拒绝

#### Scenario: Crash before native acknowledgement
- **WHEN** 预算已预留但 task 绑定或 native 回执尚未确认时进程重启
- **THEN** 恢复原意图、allocation、request/task 身份，未决派发不能生成替代操作

### Requirement: Shared allocation without double charging
系统 SHALL 在活动账户预留整轮 cap，并在轮内独立账户记实际执行用量；活动账户 MUST 不再对同一次 attempt 重复 hold。结算 SHALL 根据原持久证据单调累计，重复结算不得重复扣减或释放。

#### Scenario: Two round cumulative usage
- **WHEN** 首轮已知停止并完成实际用量结算后预留第二轮
- **THEN** 仅使用活动剩余额度，保留首轮已耗额度和原用户账本，不创建新总预算

#### Scenario: Unknown retained
- **WHEN** 原派发、效果停止或用量仍为 UNKNOWN
- **THEN** 保留原 allocation，禁止下一轮，历史 GET 不退款或触发执行

### Requirement: Verified toy baseline promotion
首版 preset SHALL 使用版本化本地 ORX toy 的独立 MSE 评价，固定 minimize 与 minimumImprovement=0。只有严格正 improvement 才晋升；平局、回退或评价失败 MUST 保留原基线并停止。晋升 SHALL 绑定原 candidate 源码产物与评价回执，不伪造 checkpoint。

#### Scenario: Improvement then tie
- **WHEN** 第一轮原 baseline/candidate 得到 MSE 16→0
- **THEN** 第二轮实际读取第一轮 candidate 字节作为 baseline，固定 candidate 得到 0→0 后停止，谱系显示 tie

#### Scenario: Untrusted evaluation or baseline
- **WHEN** 评价或源产物的 owner、原任务、内容摘要、dataset/evaluator 身份不符，或仅有模型自报数值
- **THEN** 不晋升、不派发后继，保留原证据与基线

### Requirement: Fresh authority and bounded continuation
系统 SHALL 对轮次、工具调用数和绝对 deadline 执行活动级硬限制，继续执行前重新核对成员与资源权限。新轮 MUST 不重置 deadline 或扩大通用 child/depth 限制。取消 SHALL 阻止后继并按原身份停止当前轮。

#### Scenario: Exhaustion or revocation
- **WHEN** 活动剩余额度不足、截止时间耗尽、成员/资源撤权或已取消
- **THEN** 不启动新效果，记录准确停止原因，原用量和 UNKNOWN 占用仍保留

### Requirement: Honest metering and read-only history
活动历史 SHALL 展示轮次、基线来源、已耗/预留/剩余额度和停止原因，读取不得推进执行。BYOK 缺少计量时 token/money MUST 显示 unavailable/unknown，不能显示为零或声称已硬限制。

#### Scenario: Reload with unavailable model usage
- **WHEN** 重载一个没有 token/money 计量的 BYOK 活动
- **THEN** 恢复持久谱系及真实 round/tool/deadline 限制，清楚标明计量不可用，不重新预留或派发

### Requirement: Existing operation compatibility
既有单轮、冻结 toy recipe、原任务/效果与关闭生命周期 SHALL 保持兼容；新增轮次协调 MUST 复用原 native 执行队列，不能将旧记录迁移成新的活动或以重放消除 UNKNOWN。

#### Scenario: Historical single round
- **WHEN** 新服务读取既有单轮或旧 toy 记录
- **THEN** 原 hash、运行身份、停止证据及产物可继续核对，不自动创建 successor
