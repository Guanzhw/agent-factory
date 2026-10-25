# Proposal

## Why

研究Workflow每轮结束后需保留实际结果、结算原预算并可靠发布下一轮意图。当前observer将原任务terminal后不再扫描；提前发布事件又可能因未结算的预算hold被永久拒绝。原生执行已停止但用量UNKNOWN时，需要沿原任务继续核对，不能重新执行或把账务等待伪装成仍在运行。

基线：03e1dab57ecd189ec4796dfc1463947a49a194a4。本变更只规划核心收尾契约，研究业务的具体Workflow/记录和P3后继消费者属于另一个change。

## What Changes

- 为明确装配的研究Workflow消费者提供原root事务完成边界：terminal、原allocation结算和应用记录/outbox共同提交。
- 用量HELD或完成回调失败时回滚该root完成事务，保持nonterminal并由现有observer再次核对；不新增通知表、worker或UsageLedger唤醒hook。
- 区分真实执行停止、账务结算及领域成果，维持UNKNOWN预算占用和原身份。
- 防止reserve快速释放及无run的admission_failed旁路跳过已声明消费者的收尾。
- 完成接口只写原任务关联元数据，不submit、重派或赋予新权限；后继准入继续由既有P3处理。

## Capabilities

### New Capabilities

- `owned-native-finalization`: 原生任务正向停止后的事务结算、应用完成记录及原身份重试。

### Modified Capabilities

无；当前openspec/specs尚无已归档能力。

## Impact

涉及LifecycleObserver、Store终态写入路径、LocalBudgetScopes结算和ApplicationRuntimeRegistry具体完成回调。可能影响任务状态投影及队列容量释放；需真实PostgreSQL故障/并发验证。保留Agno执行所有权，不改模型provider、凭据、UI或既有历史数据。按独立审查增加既有nativeComponent完整pin的附加owner选择，保留其他binding/effect owner，不发展通用插件框架。
