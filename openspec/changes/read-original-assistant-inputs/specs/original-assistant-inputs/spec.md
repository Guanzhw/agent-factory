## ADDED Requirements

### Requirement: Original event outcome is owner readable without creating work
The system SHALL let the current event author read the event scan status and its existing delivery status/error codes without exposing recipient execution or budget records.

#### Scenario: Rejection precedes successor task creation
- **WHEN** an event candidate is rejected before an allocation or task exists
- **THEN** the event author can read the existing rejection and endpoint reference without triggering prepare, admission or recovery
- **AND** another member receives 404 and no recipient scope, task, message or input fields are returned

### Requirement: 原任务决定事件输入身份
系统 SHALL 从当前成员自有原任务的持久request/delivery/allocation关联读取事件引用，不相信caller或agent指定内容身份，也不产生执行副作用。

#### Scenario: 自有事件任务与人工任务
- **WHEN** 当前成员读取自有任务的事件输入
- **THEN** 事件任务返回原content/event/delivery/root/depth/scope/allocation引用；没有delivery关联的人工任务返回None，不创建关联

#### Scenario: 越权或关联损坏
- **WHEN** 其他成员读取任务，或delivery/allocation不属于原owner/task/request
- **THEN** 拒绝读取，不返回替代内容或按人工任务降级，不allocate或重派

### Requirement: 可配置深度不替代预算
系统 SHALL 接受非负maxDepth而不使用固定20轮限制，继续保留原lineage、期限、候选上限和scope实际总预算。

#### Scenario: 合法较深事件链
- **WHEN** 接收者明确配置大于20的maxDepth且事件仍在该深度、TTL和既有预算内
- **THEN** 不因旧硬上限拒绝；超出已配置深度或预算仍拒绝，不重置根或创建额外额度

### Requirement: 技术错误记录不保存任意消息
系统 SHALL 只记录显式有限集合内的Factory HTTP code或异常类型；不能保存任意provider正文、敏感消息或把技术拒绝解释为科学结论。

#### Scenario: 结构化code与不安全说明
- **WHEN** HTTP错误包含集合内已知code，或只包含任意说明/其他异常文本
- **THEN** 前者保留code，后者（含全大写敏感样式文本）只保留异常类型，原delivery身份不变
