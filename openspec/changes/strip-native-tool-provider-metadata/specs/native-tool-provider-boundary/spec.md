## ADDED Requirements
### Requirement: 本地元数据不进入 provider 工具协议
系统 SHALL 在 OwnerChatModel SDK 边界复制移除 function.external_execution 布尔字段，保留原工具对象与字典；不得放宽 canonical codec。

#### Scenario: 原生等待工具通过两种协议
- **WHEN** 真实 Agno factory_wait_operations 经 OwnerChatModel 发送 Chat Completions 或 Responses
- **THEN** 合成 HTTP 收到合法工具定义而无 external_execution，原工具仍标记外部执行，原 run 可暂停并在原 requirement 完成后继续

#### Scenario: 无效元数据不得被静默丢弃
- **WHEN** external_execution 不是布尔值或工具含其他未知字段
- **THEN** 原 codec 拒绝且零 HTTP 请求，原输入不变
