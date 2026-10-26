# Proposal

## Why

基线 `62614177c23c4d2cd0caf6b7c91418e74fde8ad4`。跨 PR 审计 C1 确认：原 child 已成功停止，但普通换行、URL 或 4097 字符正文触发控制元数据校验，原 operation 永远无法闭合。需要让正常正文沿既有结果链完整到达消费者，同时保留原停止、身份和预算边界。

## What Changes

- 对精确 native-delegated adapter 的固定 output 形状分离正文与控制元数据校验；正文仍保存在同一原 operation 的 `output.result`，不增 journal、artifact 或读取服务。
- 合法 JSON 正文按原 child 的 `budget.outputBytes` 计 UTF-8 JSON 字节；不因换行、引用 URL 或普通业务键拒绝。控制元数据继续使用原严格规则与限额。
- 正向停止后若正文确实超出原输出预算或不能表示为 JSON，记录明确的技术失败并闭合原效果；不截断成成功、不变成 UNKNOWN，不改原 native 正文。
- 保持现有消费者和原记录形状兼容；用实际 custody 回归与串行 native PostgreSQL 暂停／重启／继续验证完整正文、终态和预算交接。

## Capabilities

### New Capabilities

- `delegated-workflow-operations`: 补充既有同名 change 的原结果正文合同；主 specs 当前为空，不创建平行能力名。

### Modified Capabilities

无已归档主 spec。

## Impact

生产改动限于 `platform/agent_factory/delegated_operations.py`、`workflow_contracts.py` 及必要的共享常量；不改 Research 源码及其 native component pin，不增加外部协议、依赖、公开权限或后台维护。测试覆盖原 adapter/custody、WorkflowControl、现有 Research 读取和实际 native child 等待。此方案须由非作者审查通过后实施；任务由 coordinator 核对证据后勾选。
