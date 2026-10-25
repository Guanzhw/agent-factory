# Design

## Context

动机见proposal；消费者为研究应用的实验记录/共享成果变化、定向经验询问和相关关联，不是无消费者的消息总线。已有P2消息接口在重复POST时只读，原保存后准入前崩溃明确unconfirmed。本变更在可信事件交付路径增加受限的原身份准入重入，不改变公共重复POST语义。

源码依据（当前工作树，实施时绑定精确head）：

- `Store.transaction`/`sql`借用`_connection`，`Store.event`的af_events写入因此可以加入调用者事务，但事件绑定task且只供回放，不能用其递增ID推断其他事务全部已提交。
- `Store.admit_plan`锁定owner/request并验证fingerprint，固定同一输入只返回原plan。`Store.reserve_task:264–305`在全局准入锁内按唯一(owner,request)查旧/插入；独立事务退出提交后才返回fresh。
- `FactoryAPI.instantiate:142–168`只在fresh时调用`bridge.submit`；旧task直接查询。`NativeBridge.submit`核对已持久task UUID、owner和组件，并由owner/task/request生成native幂等键。交付器不能绕过FactoryAPI直接调用bridge。
- `Store.transaction`会借用外层事务，因此以上“预留先提交”依赖没有外层事务跨越native调用；P3必须在领域/outbox、消息和allocation事务均提交后才调用异步准入，不能把整段await包进领域事务。
- `LocalBudgetScopes.allocate/bind_root`复用usage ledger锁；bind_root要求reserved且无run的原root与精确plan，已有绑定只允许相同task/plan。`UsageLedger.reserve`会纳入root allocation账户，tool入口复用`check_tool_capacity`；`settle`等待原task树、效果与用量确定。
- core-only的main当前未装配`LocalBudgetScopes`；ledger/delegation仅通过`getattr`使用可选服务。P3须显式构造单一scope服务、注册existing require_current执行guard并交给store，不可只传allocation_id却漏装实际预算检查。
- 当前`ApplicationRuns.start -> FactoryAPI.instantiate -> Store.reserve_task`没有传入allocation的端口；若先start再bind，native可先执行，存在真实预算竞态，必须修复接入顺序。
- `FactoryLifecycleObserver`只观察/清理原任务，没有消息执行职责；main的native queue仍是唯一执行worker。不能将消息扫描器加入其业务状态机。

## Goals / Non-Goals

**Goals:** 领域提交和投递intent原子，收件范围可核对，接收者显式自动预算，原身份有限恢复，可证伪的故障与并发验收。

**Non-Goals:** 不引入外部broker、P2P、任意filter DSL、新模型计费系统或第二任务状态机；不尝试把已reserved但无回执的窗口自动变成确定成功；不把通知相关性算法放core。研究QA是否禁止训练由固定应用组件与工具边界落实，本服务不靠消息文字保证。

## Decisions

### 有限事件与订阅

事件表保存稳定ID、发布者、来源命名空间/事件类型、core可授权的内容引用、有限候选端点、创建/截止时间、关联根和深度。首个消费者引用`share-scoped-application-content`发布的内容ID；core检查该内容当前读取权限，正文仍由应用解释，不读取研究项目/实验schema。没有需要就不增加任意来源解析插件；新的来源类型必须有消费者和对应spec。

应用在领域记录及curated内容发布的同一PG事务内调用emit。emit使用显式借用连接，不能独立commit；producer幂等键复用现有命令回执，同键改变来源/候选/内容冲突。应用先用领域相关性选少数候选，core只取其与receiver订阅的交集，不根据研究关键词自行选择成员，更不能缺候选时广播。

订阅由接收端owner配置：来源命名空间、事件种类、端点、scope ID、单次预算、deadline、传播深度及候选上限。范围采用精确匹配，不开放任意表达式；启停/变更形成明确新配置，已交付消息的身份不变。预算承诺必须明确建立，默认不自动续期/扩额。实际数值在配置/正式验收前固定，不在设计中臆造20人容量阈值。

### outbox与消息交付

交付表以(event ID, endpoint ID)唯一，关联固定消息请求键、allocation ID和当前投递结果。待交付记录用有界批次扫描，不以全局最后ID跳过可能晚提交的事务。交付可以有多个并发扫描者，但只创建同一消息/分配；扫描器是消息交付维护任务，不是执行worker。

在短事务内核对当前成员/端点/来源可读、订阅匹配、TTL/depth和剩余scope，幂等allocate并记录消息intent，随后提交事务。只有明确已提交的intent能进入准入。取消/过期前已经创建的task仍保留，禁止通过删除投递记录释放UNKNOWN。当前无原task的过期分配保守保留，除非在同一准入栅栏内有明确未提交证明；不得凭查询404释放。

交付器生命周期由core显式装配，native queue ready后开始，关闭时停止新交付再按既有关闭期限结束维护；不等待它自行完成研究。它只调用消息/准入服务、查询原收据及existing settle，不直接执行工具、驱动训练或接管取消。临时依赖错误保留可观察错误类别并有界重试元数据交付；不吞错、不另启恢复任务。

### 原请求恢复：选择与证明边界

准入恢复策略：可信交付恢复路径只对未存在task的消息，以相同owner、固定endpoint defaults、文本和原ApplicationRuns request ID重入`ApplicationRuns.start`，绝不生成替代ID。公开重复POST仍只读。读取absence不是单独授权；安全性依赖后续已有准入原子fresh判定：

1. admit_plan在owner/request锁下返回同一不可变plan；配置和输入漂移冲突。
2. 多个发送者/恢复者即使都先读到无task，最终在reserve_task全局准入锁下只有一方插入并获得fresh；其他方看到原task，不能调用bridge。
3. task插入事务及预算绑定提交后才可能native提交。禁止在未提交的外层事务里await准入，否则此证明不成立。
4. 已存在reserved/unknown/accepted task的恢复只读取原状态；发生“task提交后、bridge调用前”崩溃仍可能永久不确定。不能重新给旧task返回fresh，也不能直接补调用bridge；保持UNKNOWN/hold，报告人工核对或后续有证明恢复契约需求。
5. native已接纳但metadata回执丢失时只用现有原身份查询；匹配原native ticket才可按既有接口绑定，未找到不是未执行证明。

因此本设计解决消息已持久且尚无task的准入恢复，不保证所有崩溃窗口最终执行。reserved无回执窗口的自动恢复明确BLOCKED，不得以重试次数、超时或重启代替证明。实施前必须以真实PG事务屏障证明上述顺序及并发唯一性；仅mock start计数不够。

### 预算先于native派发

跨界实现：增加最小可信keyword `allocation_id`，沿`ApplicationRuns.start -> FactoryAPI.instantiate -> Store.reserve_task`传递；不加入HTTP `InstanceRequest`，不接受发送者指定他人scope，不设计callback插件框架。新task的`LocalBudgetScopes.bind_root(conn, owner, allocation_id, task_id, digest(plan))`在原reserve事务里完成，失败整体回滚；核对与现有ledger/准入路径的锁顺序，避免usage锁反向等待admission锁。没有allocation的既有人工启动保持原行为。

如果原task已存在，必须核对它原来已绑定同一allocation/scope/plan，不能晚绑定已运行task或换scope。模型调用继续使用既有ledger/attempt账户，工具预算沿既有guard。事件重复只用同一allocation ID，不再次分配；UNKNOWN用量保留，终态结算调用existing settle且只结算一次。额度不足或owner停用明确拒绝新执行，不能自动借用发送者模型/预算。

LocalBudgetScopes当前caps要求toolCalls至少1，不能把0传入冒充“无工具QA”；QA无训练必须由后续固定无训练组件/工具入口证明。无法准确计价的BYOK使用既有unmetered语义和明确有限轮次/工具/时间，不宣称金额硬上限。receiver scope到期限制新准入，并由existing guard阻止后续调用；不能把deadline直接当作外部进程已停止。

### 撤权与准入线性化

新task和allocation绑定事务提交为准入点。reserve_task持有既有af_admission锁，通过可信delivery_id读取持久接收者、原request、端点、content、订阅与allocation并核对plan/request；仅fresh分支检查当前交付授权，旧task只核对原绑定。content.set_visibility、endpoint.set_enabled及subscription禁用在同一Store事务中先取af_admission，再取各GovernedStorage namespace锁并更新；不修改通用ResourceSharing.set，不扩大为全资源锁。准入中的授权检查只借用连接读，不取namespace写锁；固定顺序admission→namespace或usage，禁止持有namespace/usage后进入准入。消息intent/allocation必须先提交，FactoryAPI拒绝外层未提交Store事务跨native await。

两方向真实PG屏障验证：检查后暂停，撤权先提交，恢复必须零fresh dispatch；准入先提交则撤回不能改变原task/allocation或重派。账号停用使用现有当前成员检查及执行guard，不宣称其外部authority参与本PG锁或得到同等原子保证。

### 原请求的强制预算关联

独立P5审查发现prepared handoff可经普通instances入口省略allocation参数先准入，故仅可信keyword不足。新增LocalBudgetScopes.bind_request(conn,owner,allocation_id,request_id)，在原启动intent事务内持久唯一owner/request→allocation及可选delivery_id关联；所有reserve入口在af_admission锁内读取该关联并强制预算及delivery授权检查，即使调用方没有传allocation。ApplicationRuns带allocation时在admit_plan前提交该关联；事件prepare与研究start intent在同事务提前绑定。

固定锁序admission→namespace→usage，调用方准备intent时先拿admission；bind_request本身重入admission后取usage，不能在未取admission时先持usage。此前已有无预算task不得事后采用；相同request/原allocation幂等，换allocation拒绝。持久关联既不授予owner权限，也不创建task；预算化request只能使用既有admit_plan保存的原plan，计划尚未准备、替换为另一plan或复用已绑定plan改request均拒绝；本地scope绑定的原请求/plan不能转成远端root，必须在实际HandoffClient reserve的admission栅栏内拒绝而非仅检查HTTP kwargs；scope关闭后的普通入口仍拒绝。真实PG在plan已保存/尚未reserve屏障调用公开instances，证明其同样受绑定与scope约束。

### 循环与权限

关联根和深度由可信事件发出上下文继承，不允许agent生成新根逃逸同一自动链预算。每个订阅scope有总轮次/调用上限；候选数量、事件期限、最大深度和scope deadline同时约束，不能仅靠“不要循环”的prompt。新用户明确请求可建立新研究/预算承诺，自动回复不能自行续期。

交付前及恢复准入前重查当前读取权限和端点owner状态；撤权已提交后开始的新准入必须拒绝。先前已交付字节不能回收，已准入任务由现有权限guard和取消/恢复语义管理。交付状态仅说明intent/消息/拒绝/过期，不复制native完成状态；页面通过原收据投影说明执行是否确认。

## Risks / Trade-offs

- [task已预留但无native回执] → 原身份观察，保留预算/UNKNOWN；自动补派不在本方案内，明确BLOCKED。
- [预算绑定晚于执行或外层事务未提交] → root只在reserve原事务绑定；故障屏障验证bridge无法在commit前运行。
- [应用事务独立写outbox] → 同连接提交/回滚与跨连接可见性测试，禁止用异步后台补发替代原子提交。
- [扫描器成为第二控制链] → 无业务执行/取消接口，受现有生命周期停止，所有执行走原native准入。
- [无关或恶意来源触发成本] → 候选与订阅交集、当前内容权限、receiver有限预算、depth/TTL；相关性价值另用真实模型C03验收。

## Migration Plan

新增事件/订阅/投递表，默认无订阅、不迁移旧事件为自动执行。P1/P2原请求及人工API保持兼容；可信恢复与allocation关键字只供显式消费者。先实现并验证预算原子绑定和原请求恢复，再接outbox、订阅与维护生命周期，最后由研究应用接入。每单元有作者之外完整diff精简审查，检查spec本身是否过度设计；回退停止订阅入口/维护，不删除原消息/task/预算证据。

### 最小服务契约（实施前核定）

`AssistantEvents(store,auth,endpoints,content,messages,scopes)`提供`configure`、`set_enabled`、同连接`emit`、短事务`prepare`、只读`validate_admission`和有界`deliver_batch`。订阅配置包含endpointId/namespace/eventType/scopeId/caps/deadline/maxDepth/maxCandidates；同(endpoint,namespace,eventType)仅一个enabled配置，变更先停旧配置再新建。原delivery固定原subscription，不随新配置改绑。

`emit(conn,owner,event,request_id,parent_delivery_id=None,task_id=None)`的event仅含namespace/eventType/contentId/candidates/deadline；必须借用当前领域事务。自动事件传原delivery及绑定task，从持久记录继承root/depth/deadline，不能传入自选root/depth。消息正文为有限内容引用，应用以接收者身份读取内容。

`prepare(event_id,endpoint_id)`在namespace→usage/messages锁序内建立唯一(event,endpoint)delivery、receiver allocation和原message后提交；不得跨事务调用native。缺scope不自动建无限预算。`validate_admission(conn,owner,delivery_id,request_id,plan,allocation_id)`在既有admission锁内只读核对原tuple、配置pin与当前授权，不额外创建hash证明链。订阅启停先admission→namespace；旧delivery不改绑。`deliver_batch`只显式调用，无自启动线程，生命周期由core装配。

### 单项失败与有界公平扫描

每个事件和pending交付记录最近尝试时间及错误类别，按最近尝试时间轮转；既有维护循环每秒一批限制元数据重试速率，不新增独立重试平台。单项依赖/未知异常不能阻止本批后项，错误仅保存类别，避免把任意异常参数写入记录。终局4xx在admission锁内检查原request尚无task后才标拒绝/过期，allocation保守保留；fresh准入同时要求delivery仍pending，防止已暂停的recover在拒绝提交后再准入。已有原task继续只观察和结算，UNKNOWN不释放。此处轮转不把运行失败自动变成新消息或新执行。
