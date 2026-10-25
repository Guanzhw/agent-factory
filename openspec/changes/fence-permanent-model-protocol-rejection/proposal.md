## Why
551f1bf 的真实无工具问答在拒绝恶意 train 响应后，原队列 attempt2 重跑整个工作流并再次请求模型。单例与正常问答前序组合均复现；正确的单请求provider校验不能阻止原队列重试。

## What Changes
在可信模型调度边界持久化原任务明确协议拒绝及现有取消执行栅栏；原队列可以重试但不得再次调用供应商或工具。既有observer按失败原因清理与结算。

## Capabilities
### New Capabilities
- `native-protocol-rejection-fence`: 已知永久协议拒绝在原task/run上持久终止后续执行授权。

## Impact
仅core model_dispatch、Store最小事务接缝与针对性测试。无全局retry变化、Agno私有worker修改、第二状态机或应用特判。
