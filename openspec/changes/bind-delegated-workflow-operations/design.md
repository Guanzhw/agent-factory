# Design

## Context

基线f25c8992f5c286db3cca3554e3c74a255dfe9f82，动机见proposal。`native_workflows.py::_wrap`允许治理函数声明run_context/application_context并在原root校验、工具授权和预算消费后注入。`OperationCustody.start`已持久原operation后才await运行时；重复slot不再次start。`DelegationService.create`拥有child准入/原请求去重，public观察/取消重查成员；`WorkflowControl`只沿原requirement继续。当前基础DelegationService拒绝placement。

## Goals / Non-Goals

**Goals:** 在同一个既有控制链中连接原操作、原child和原native等待；已撤权时仍能清理原效果，不能开始新效果。

**Non-Goals:** 不新增ApplicationExecutionContext端口、队列、调度/恢复worker、credential管理或任意服务容器；不实现研究策略、远程placement、GPU后端或UI；不把合成运行当C类模型自主通过。

## Decisions

### 1. 最小接口与静态装配

core提供一个遵守既有运行时协议的delegated-operation adapter，可信composition注入DelegationService及其原身份观察/取消能力。保持四个接口：

- `start(context, operation_id, inputs)`
- `inspect(context, handle)`
- `lookup(context, operation_id)`
- `cancel(context, handle)`

context使用既有WorkflowContext，含owner_id、workflow_id（这里是原parent taskId）、run_id、stage_id和definition_sha256。不把它当外部调用者可声明的身份：每次调用核对原OperationCustody记录、parent task/run/plan及选定adapter pin，再核对child link；仅操作该原记录。

inputs最初仅goal/mode，均使用现有有界校验。parent/owner/request/placement不能来自模型输入。adapter id/revision/configFingerprint由装配固定，并在OperationCustody记录精确保存。实现不加载输入提供的import或注册任意执行器。

研究治理函数直接接受已验证run_context，闭包注入单一OperationCustody.start callable，固定step/effect_slot/adapter_pin后传入模型提出且已校验的goal/mode。无需扩展公共application_context或暴露Store。注册与服务绑定须在启动执行前完成；不为该消费者添加通用延迟服务发现框架。

### 2. 原operation到原child唯一映射

原operation ID确定唯一child request，例如`operation:<operation_id>`；调用现有DelegationService.create(owner,parentTaskId,goal,mode,requestId)。child始终由DelegationService/native queue执行；adapter不直接submit或创建第二task。child权限/工具是祖先子集，沿原root LocalBudgetScopes和delegation预算消费，不另bind_root或创建scope。

handle保留原operation ID及既有adapter身份，child由原operation对应唯一link解析；OperationCustody已保存原operation与请求摘要，不再复制执行状态机。查询按原parent/request查唯一delegation link，核对owner/plan/child及原运行身份；找到link不等于已执行，缺child/native回执仍UNKNOWN。相同operation重复调用不能制造新child；不同goal/mode与原请求冲突应拒绝，不能“修复”成新request。

如果create回执丢失，adapter抛既有WorkflowAcknowledgementUnknown保留原operation。lookup只查询原link/task，绝不调用create、重新submit或重设原request。缺link本身不能证明未dispatch；缺失保持UNKNOWN。取消前未dispatch的关闭证明仅在已有原身份锁/取消边界阻止迟到start并确认无原效果时才成立；本次不添加盲目补派兜底。

### 3. 子树观察与撤权清理

inspect/lookup观察原child及其后代的native/effect/custody事实；不包含父task正在持有的当前OperationCustody，否则父操作等自己关闭、永远allStopped=false。输出沿既有RuntimeObservation保存原child结果、实际产物引用和失败事实；native completed不解释为科学达标，UNKNOWN不填零值。allStopped只接受子树正向停止证明，不能来自调用cancel成功或墙钟超时。

正常start继续执行全部当前成员/祖先/预算检查。观察与取消则由core内部窄桥接在核对原operation和child绑定后复用FactoryLifecycleObserver的原ticket/session核对、_facts与_cancel_bound路径，允许成员禁用、应用撤回或父授权结束后的原效果收尾。不能直接复用仍require_member的public children/cascade_cancel作为唯一cleanup路径，也不能在research调用私有方法绕过授权。可信装配注入observer的inspect_subtree(owner,child_id)/cancel_subtree(owner,child_id)，先通过原root全树校验，再只观察/取消child子树；不调用observe_root提前终结整个root。桥接不得允许新create，不新增无认证HTTP。

父停止或scope取消后，child下一模型/工具入口仍按原guard拒绝；已有效果只能观察/取消。cancel作用于该原child子树，不取消无关兄弟任务或把父状态当已停止证明。原cleanup错误保留可观察UNKNOWN，不吞错、换句柄或重建运行。

### 4. 复用原native等待与生命周期

固定研究Workflow的治理函数启动operation后，现有factory_wait_operations等待该operation ID。已有observer/application observe_waits只核对既有operation；闭合后沿原WorkflowControl requirement和命令恢复模型，使模型收到实际结果。adapter不拥有observer、continue_run或新的轮询器。

服务重启需以同一adapter pin恢复注册，再沿原operation/child/requirement读取。缺原运行时实现时保留custody，不能以新版本接管。普通Agent wait恢复、任意Step工具放开均不在范围。完成后的预算/结果/outbox使用已存在的原group事务完成机制，不在adapter重复实现收尾。

### 5. 具体机制验收

使用真实PG和实际原生Workflow/child队列，模型输出可用清楚标识的合成fixture：启动child、原wait实际paused、服务重启、child结束、原requirement继续，断言实际工具输出进入后续模型Step。另覆盖create丢回执后lookup零create、观察child子树不被父operation自阻塞、父scope取消和成员禁用后零新dispatch且原child可停止、双operation互换handle被拒绝、重复reconcile不生成新child。

锁与等待沿现有root/admission/metadata协议，数据库连接不跨adapter await；core独立review需检查必要桥接是否只是原身份收尾，而非第二权限或恢复系统。首失败保留，重型PG由coordinator串行。

## Risks / Trade-offs

- [原start在持久operation后尚未dispatch即退出] → lookup保守UNKNOWN；不为可用性新增create重试，确需无dispatch关闭须有正向原取消证明。
- [父custody参与child停止判断导致循环] → 测试父operation仍open时已停止child返回allStopped=true。
- [撤权cleanup被public成员检查阻断或过宽绕过] → core窄原身份桥接，分别证明不可newcreate、可停止原child、不可操作其他owner/task。
- [被误当成远端GPU能力] → 当前仅本地native child；placement仍明确拒绝，选定远程runtime另行适配和验收。

## Migration Plan

先独立core spec/review，再实现adapter与原身份桥接；真实native等待/重启测试通过后研究Workflow才注册该精确pin。已存在operation保留原pin与数据，不清库、不改历史身份。撤下实现保留原记录并呈现缺失运行时，不能宣布清理完成。真实模型与实际GPU验收不在本次机制结果中。

### 实施接口核对

WorkflowContext不含effectSlot；adapter核对parent/run/stage/plan/pin，custody负责将每个原operation自己的持久handle送入adapter。同一context内其他合法operation不靠新增hash或扩大context做虚假的跨slot证明。静态constructor为DelegatedOperations(delegation, observer, pin)，由composition在现有服务创建后注册；不新增运行时服务发现。输出遵守现有RuntimeObservation的有界inert契约，携带实际child内容与artifact身份，不截断伪造结果；任意大/不适配正文需由既有artifact读取边界获取。

单操作取消线性化复用原root advisory锁：custody先持久cancelRequested，adapter取消在同root锁查询child；create在已有root锁内核对original_operation_id、parent/run/plan、输入摘要及cancelRequested后才写link，native提交前再查。create先取得锁则取消可见其已提交child；取消先取得锁且未见child则后来的create被拒绝。无child仍UNKNOWN，不把标记当无dispatch证明。

普通DelegationService.create入口保留并拒绝`operation:`请求namespace；只有可信adapter提供original_operation_id时才允许，并在原root锁内验证固定adapter pin、parent/run/plan、输入摘要、原request与取消状态。HTTP/工具普通委派不能仅猜到operation ID就绕过该核对；无link的已取消custody通过公开HTTP同request申请仍须zerochild/zerodispatch。

子树停止观察也在原root advisory锁内重读完整关联并收集facts（同步工作在线程中，不跨await持锁）；不能在后代create已持锁但尚未提交link时依据旧集合allStopped闭合父custody。真实barrier测试要求观察等待原锁，释放创建后包含新后代，未停/UNKNOWN保留custody。
