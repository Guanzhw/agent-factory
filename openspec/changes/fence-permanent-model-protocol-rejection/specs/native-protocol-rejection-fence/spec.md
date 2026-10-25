## ADDED Requirements
### Requirement: 永久协议拒绝在原任务持久禁止后续执行
Core SHALL 在可信原task/run模型调用收到精确PERSONAL_MODEL_TOOL_NOT_DECLARED后，原子记录protected failure及现有执行取消栅栏，再将错误交回原生运行时。

#### Scenario: observer之前队列再次尝试
- **WHEN** 原队列attempt2早于observer清理运行
- **THEN** 同task/run不能再次请求供应商或执行工具，原任务最终为failed且保留失败来源

#### Scenario: 普通错误仍遵循原重试策略
- **WHEN** 模型返回其他普通错误
- **THEN** 不设置此协议拒绝栅栏，原队列策略不变

#### Scenario: 原身份与事务失败
- **WHEN** task/owner/run不匹配或失败记录与取消写入中任一步失败
- **THEN** 不对其他任务建立栅栏，不提交部分状态，不宣称失败事务已持久化

#### Scenario: 账务与原操作状态保持
- **WHEN** sync、async或stream模型调用被拒绝
- **THEN** 原账务完成路径仍运行，UNKNOWN效果不被假定停止，结算仍由原生命周期处理
