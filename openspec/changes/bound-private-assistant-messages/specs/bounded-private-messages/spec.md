## ADDED Requirements

### Requirement: Ordinary budgeted roots finish through existing atomic settlement
The system SHALL settle an original allocation through the existing native completion transaction even when no application completion callback is registered.

#### Scenario: Stopped root retains an unresolved budget hold
- **WHEN** the original native task tree is positively stopped but usage settlement remains HELD
- **THEN** terminal/reclaim and settlement roll back together and the same observer can finish the original root later
- **AND** no new dispatch, receipt-side mutation or application-specific completion owner is required

### Requirement: 接收者明确的有限消息预算

系统 SHALL 允许owner为endpoint固定配置自己的scope/caps/deadline；每条新消息沿原request最多分配一个allocation。未配置endpoint保留已有行为，不为旧消息回填预算。

#### Scenario: 正常私密发送
- **WHEN** Alice向Bob已配置预算的endpoint发送经验问题
- **THEN** 消息、Bob的allocation及原request映射共同提交，只有原fresh准入可派发，消息仍仅双方可读且不发布团队content

#### Scenario: 非法承诺
- **WHEN** 配置外人scope、失效scope、非法caps或超出scope期限
- **THEN** 配置失败，不能花费他人预算或自动扩容

#### Scenario: 同键重投与事务回滚
- **WHEN** 并发同键发送、同键异内容或事务故障
- **THEN** 同内容复用原收据且不重复hold/submit，异内容冲突，事务失败无孤立消息或hold

### Requirement: fresh准入重查及原身份恢复

所有预算消息fresh reservation SHALL 在既有admission锁内核对当前端点、双方成员、原allocation及预算，不建立第二执行恢复链。

#### Scenario: 保存后撤权
- **WHEN** prepare后reserve前禁用endpoint/成员或取消scope、到达deadline
- **THEN** 新task/dispatch为零，直接普通instances入口同样不能绕过

#### Scenario: 保存后进程退出
- **WHEN** 消息与allocation已提交但task尚未存在
- **THEN** unconfirmed及原hold保留，显式可信recover仅以原request/allocation进入原fresh gate

#### Scenario: 已有未知任务
- **WHEN** 原task已reserved或UNKNOWN，随后endpoint或scope到期
- **THEN** 重复发送/恢复只查原收据，不重派；原停止核对和清理不被新准入期限阻塞

### Requirement: P3沿同一接收者allocation

P3送达预算endpoint SHALL 复用其原allocation/request，不额外分配。

#### Scenario: 已有事件承诺
- **WHEN** P3 prepare已有allocation且subscription匹配endpoint承诺
- **THEN** 消息映射沿原allocation，最终一个hold/task；不匹配scope/caps/owner明确拒绝

### Requirement: 接收者读取原task消息输入

系统 SHALL 提供只读原task→message端口，保持当前成员和精确receiver/request/task/allocation/delivery关系，不扩大内容可见性。

#### Scenario: 合法原任务读取
- **WHEN** Bob读取自己原message task的输入
- **THEN** 返回原sender/recipient/endpoint/text，不访问对方job或凭据，不产生执行

#### Scenario: 伪造或损坏关联
- **WHEN** 外人task、request、allocation或delivery不匹配，或消息命名空间中缺记录
- **THEN** 明确拒绝；普通非消息task才返回None，不能把损坏关联当作无消息

#### Scenario: 同目标替换绑定不能旁路
- **WHEN** 普通instances使用同app/mode/goal但改变materialChoices、connectionRefs或inputValues的prepared plan请求预算消息原身份
- **THEN** 完整规范请求与原af_plan_requests fingerprint不匹配，fresh准入拒绝且零dispatch，不建立额外hash表
