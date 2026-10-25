## Context
基线551f1bf。原full日志/tmp/af-qa-full-first-pg.log。隔离单例1test/1failure10.513s，正常→恶意组合2tests/1failure22.725s，日志/tmp/qa-retry-single-first.log与/tmp/qa-retry-pair-first.log。恶意同task/run/request/plan，队列attempt1后attempt2、max_attempts2；每次均PERSONAL_MODEL_TOOL_NOT_DECLARED。
Agno Agent把模型错误变为ERROR，Workflow再返回ERROR；QueueWorker按配置重试原job，私有permanent分类器仅对逃出component.arun的异常生效。旧单次通过不能关闭observer与队列的时序竞争。

## Goals / Non-Goals
在错误交回Agno前持久拒绝后续原任务执行；失败语义不是用户主动取消。不改变普通错误的合法重试、费用证据或原operation UNKNOWN custody，不改Agno，不新增worker或状态表。

## Decisions
1. DelegatingModel._complete_selection持有已经核验的原root RunContext。向现有_guard_provider_calls传入窄的原任务拒绝回调；只有ModelProviderError且安全code精确等于PERSONAL_MODEL_TOOL_NOT_DECLARED才调用，不扩展到全部模型错误。WorkflowDecisionModel已经转成可信root上下文，无应用身份猜测。
2. Store新增窄方法，在一个metadata事务内按task id+owner+原run精确锁定行，记录protected_denied（固定安全code，不存模型文本），复用request_cancel设置cancel_requested与既有application mark_cancel。事务提交完成后才把原安全错误继续交回Agno。不调用native cancel、不自行标terminal或释放UNKNOWN。
3. 下一queue attempt仍复用原job；model dispatch current/local_current及工具既有授权读取cancel_requested，在供应商/工具之前拒绝。observer看到protected_denied，终态判failed并复用正向停止证明、原预算settle与finalizer。无需observer产品改动。
4. 四种sync/async/stream入口在捕获已知拒绝时执行同一回调。原账务finish/finally继续运行；回调不得吞掉账务失败，账务失败亦不能跳过永久拒绝的执行栅栏。两者出错应显式失败，不谎称事务已提交。数据库不可用时不能声称已经持久栅栏；不引入内存替代状态。
5. 不把新字段加入所有Task schema，不使用错误文字通配，不改现有queue_max_attempts。

## Risks / Trade-offs
request_cancel包含app mark_cancel；复用同事务职责，若任一写入失败整组回滚，不产生仅取消而无失败来源的部分提交。当前异步调用必须通过to_thread执行阻塞事务，不在eventloop内等待metadata锁。原始错误保留安全code；最终用户侧failed依靠已有protectedfailure优先级。

## Verification
便携测试四种入口的原错误、账务调用、仅精确code触发、普通错误不触发。真实PG先暂停observer，等待实际队列attempt2结束，证明同task/run原身份、provider仅1HTTP、零工具；随后释放observer验证failed/原scope结算。正常合法retry作为负对照，不能以全局关闭retry通过。原QA断言不放宽，不重复full。事务失败回滚与重启后栅栏仍存在要用真实PG，未运行不得声称。
