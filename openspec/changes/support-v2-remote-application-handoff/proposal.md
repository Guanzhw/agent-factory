# Proposal

## Why

通用 v2 应用已能本地执行，但远程 reader 仅接受 v1，成员无法保留 schema、输入、配置与 operationSeconds 完成同一应用的远程执行。本变更为明确支持的 receiver 增加根任务 v2 handoff，并保留原操作身份与冻结的 v1 兼容性。

## What Changes

- 增加严格版本化 v2 envelope，携带完整不可变应用定义及原计划；定义通过 applicationRef 的版本摘要绑定，计划继续使用既有 manifest hash。
- 目标声明 supportedApplicationContracts，默认仅 v1，v2 显式启用；receiver prepare 独立校验实际支持范围，不自动降级。
- authority、恢复和预算路径保留 v2 operationSeconds，拒绝混合版本预算。
- 首版限定根任务及选定的确定性 native agent runtime；拒绝 workflow、scientific、delegation 和嵌套 placement。
- 使用 checksum-neutral 验证真实双服务执行、准确产物和原身份恢复；目标页面显示声明的能力限制。

## Capabilities

### New Capabilities

- `remote-application-handoff`: 版本化应用远程传输、能力声明、预算及原操作恢复。

### Modified Capabilities

无。当前仓库没有已发布 OpenSpec specs；既有 v1 行为作为本能力的兼容要求保留。

## Impact

生产边界包括 remote_handoff.py、remote_authority.py、remote_bindings.py、目标描述 API 与对应客户端展示；复用 ApplicationService 版本摘要、application_schema 和 composition 的既有校验。测试使用现有 checksum-neutral、native-checksum-v1 与确定性 model，不调用真实外部模型。此规划基于独立工作树 b50d196（已合并 #97），不引入 #99 服务图重构，不改变 UNKNOWN、stop proof、权限或取消语义。
