# Design

## Context

参见proposal。P2消息有固定recipient、endpoint和sender幂等command；原应用request为`application-start:assistant-message:<messageId>`。LocalBudgetScopes已有allocate、bind_request、request_allocation/request_delivery与reserve原request/plan约束。endpoint配置当前创建后不修改，只有enable/disable。

## Goals / Non-Goals

目标：owner明确承诺有限接收预算，所有P2入口不能绕过；沿原task读取问句，保持双方私密。非目标：私人聊天产品、公共问题发布、第二恢复器、付费模型验收、新工具沙箱或配置可变版本系统。

## Decisions

### 1. 可选固定预算配置

EndpointConfiguration新增可选`automaticBudget: {scopeId, caps, deadline}`；复用LocalBudgetScopes的caps规范，单次rounds必须为1。owner配置时验证scope归属、ACTIVE、未来deadline且不晚于scope deadline、计量维度兼容及caps可适用。存于既有configuration JSON，无新表或历史消息回填。未配置endpoint保持旧P2行为。公共summary不暴露预算或连接；owner详情可读配置。

配置检查不是当前执行授权。新准入再核对当前成员、enabled、scope状态、配置deadline和额度。配置不可变，所以历史未预算endpoint不会被悄悄升级；更改承诺需新endpoint。启停仍使用既有admission锁。

### 2. 保存与预算同事务

预算endpoint的新消息：Store.transaction → LocalBudgetScopes.admission_lock → 原message namespace锁 → usage ledger锁。保存消息、allocate一次、bind_request原应用request及sender幂等command共同提交。没有provider/native await处于事务内。任一失败回滚消息及hold。

重复sender/request先返回原消息，既不allocate也不start；同键异内容冲突。过期后重复POST仍能读取原收据，读消息只验证当前双方身份，不要求预算仍可执行。

首次唯一提交者在事务后用持久allocation调用ApplicationRuns.start。保存后/准入前崩溃保留原hold及unconfirmed收据；仅显式可信recover在原task不存在时沿原request重入。reserve fresh gate唯一决定submit。已有reserved/UNKNOWN仅查原状态，不新分配、不换request。缺失/冲突预算映射拒绝，不猜测可回填。

### 3. 最小core接点（coordinator集成）

- `AssistantMessages.validate_admission(conn, owner, request_id, plan, allocation_id)`：同步、无提交。Store.reserve_task在现有admission事务内、仅fresh task分支调用；预算消息重查原message.recipient、endpoint owner/enabled、双方当前成员、原默认application/mode/goal、request/allocation、scope/caps/deadline。非消息请求和未配置预算endpoint保持既有路径。普通instances同原request/plan也必须经过该hook，不能省略allocation逃逸。已存在task只沿现有身份检查/观察路径，不因scope/endpoint到期拒绝cleanup。
- main将当前AssistantMessages实例装配到Store；不用任意callback插件表，不改变HTTP InstanceRequest字段。
- `recover(recipient, identifier, *, allocation_id=None, delivery_id=None)`：预算消息读取原映射；调用者提供的allocation必须一致。未配置endpoint保留现有可信恢复语义。
- `_reserve(sender, endpoint_id, body, *, allocation_id=None, delivery_id=None)`：后两个参数仅可信内部P3调用，HTTP不接受。有已分配allocation时核对并绑定，绝不再allocate。

### 4. P3同一预算

AssistantEvents.prepare已先分配allocation：将原allocation/delivery传入_reserve，由消息事务复用原request绑定。P3配置预算endpoint时，subscription scope/caps必须与endpoint automaticBudget一致；有效截止时间受双方deadline约束。已有不带automaticBudget的endpoint/P3行为保持。当前订阅撤回和event权限检查仍由P3 validate_admission负责，消息hook不能替代它。

锁序不得倒置：P3外层已持admission/namespace/usage锁，嵌套_reserve复用同conn与已持admission锁。直接P2也先admission再namespace。禁止持namespace后另取admission。

### 5. 只读原输入

`message_for_task(owner, task_id)`：require_member及Store.task(owner)，由原task.request_id解析消息，验证recipient/endpoint owner和原request完全一致。预算消息继续核对request_allocation、allocation.task_id、scope；有delivery映射时交叉核对原delivery.message_id/owner/allocation。返回`{messageId,senderId,recipientId,endpointId,text}`，不返回凭据/plan handoff/对方job。普通非消息task返回None；消息命名空间下缺记录或冲突映射明确错误，不伪装普通任务。读取不创建执行、不要求尚有可花预算、不自动发布ApplicationContent。

## Risks / Trade-offs

- 私密问句通过团队content泄露 → 本路径不调用content.publish，既有双方read边界保持。
- prepare到reserve间撤权 → 共用admission锁的fresh准入重查，barrier验证普通HTTP旁路同样零dispatch。
- P3双重hold → supplied original allocation与request映射一次绑定，真实PG核对计数。
- 计量不可用 → 保留现有metering unavailable/UNKNOWN语义，不声明零费用或隐式退款。
- 此预算配置不保证QA零GPU → 应用单独声明tool-free QA及受治理只读/记录函数，并实际计数验证。

## Migration Plan

仅新endpoint JSON可选字段，无新表；旧configuration读时缺字段视为无配置。既有未预算消息/任务不回填新scope。撤回时禁用endpoint，保留旧收据和原清理身份。
