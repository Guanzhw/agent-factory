# Design

## Context

动机见proposal。现有core实际端口为 `platform/agent_factory/application_interface.py` 的start/request/query/cancel/events/artifacts，`ApplicationExecutionContext`仅提供原run身份、输入、资源引用、事件和产物写入；它不是新执行器。`delegation.py`提供原生child与级联取消，`local_budget_scopes.py`提供scope/allocation/root绑定及UNKNOWN持有，`native_workflows.py`验证原生组件pin。`deployment/agent_factory_server/application_composition.py`显式安装并管理应用生命周期，core wheel不含应用。

本change仅在独立应用目录实现研究业务，不复制旧Research/OR代码。上位依据为docs/plans/research-platform-delivery-plan.md及research-platform-acceptance-contract.md；17项验收定义结果，不将本设计或合成测试写成真实科学验收。

## Goals / Non-Goals

**Goals:** 完成P4–P8全旅程；首先可独立交付项目/约定/个人助手入口，再接受控自主执行、共享记录与团队协作，最终P9综合验证。

**Non-Goals:** 不造通用PersonalAgent、另一套执行队列/恢复器/credential vault/团队ACL，不恢复旧应用，不把OR列为主链依赖，不实施未确认的全空间共享或评论/分支权限，不为假想插件制作接口框架。

## Decisions

### 1. 应用装配与目录边界

新应用置于 `applications/research/`（Python包）和 `web/apps/research/`，经明确部署/浏览器装配选择安装；core默认无应用保持不变。修改架构映射仅加入精确目录与composition入口，不豁免整个deployment目录。应用服务持有core提供的实例引用，不反向注册研究schema到core；撤下应用保留数据和原task记录，不执行破坏性迁移。

### 2. 最小领域状态，执行事实单一来源

持久内容只包含成员助手关系、项目、不可变目标版本、实验假设/条件、运行引用、记录修订与成果引用。每一运行引用原task/run/request及goal版本，不能另存一套可独立推进的任务状态机。研究状态与原操作状态分别投影：项目可未达标结束而某effect仍UNKNOWN。数据库命令复用既有幂等/事务工具；稳定ID和版本比较用于原请求与并发编辑，不为每个内部字段再做hash链。

个人助手使用P1端点稳定身份；应用记忆是本人项目约定、观察和有出处的摘要，跨多次有界native任务持久，不要求常驻推理。团队检索只读发布研究记录，不把个人聊天汇总为公共记忆。

### P4 首单元 HTTP 契约

应用router前缀 `/api/factory/research`，复用现有认证和前端request。项目创建只要求title，可选关联自己的assistantId，不要求先有任务。GET `/projects`支持after/limit，返回items/nextCursor；GET `/projects/{id}`只对owner返回详情。POST `/projects`使用requestId与title、assistantId；POST `/{id}/goals`使用requestId、expectedVersion及agreement，CAS追加目标；POST `/{id}/confirm`确认当前版本；POST `/{id}/end`用expectedVersion及outcome（not_met/cancelled）、reason保存领域结束理由。所有POST均为owner幂等命令。

agreement包括objective、evaluation、stopConditions、resourceRefs（slot到已有资源ref）和budget；budget沿core本地scope的rounds/toolCalls/tokenLimit/amountMicros/currency语义，P4仅保存约定，不建立scope、不声称资源已准入。tokenLimit为空时amountMicros/currency同时为空，否则金额非负且币种为USD/EUR/CNY。模型/连接仍在core配置，不收集秘密值。

项目详情含id/ownerId/title/assistantId/state（draft/ready/ended）、currentGoalVersion、goals历史（version、agreement、createdAt、confirmedAt）、ending和createdAt。新建version0；goal修订变draft，确认后ready；结束后拒绝修订。ending含outcome/reason/endedAt/goalVersion以及resourceCleanup=not_observed，不伪称停止或释放。P4响应execution.available=false与RESEARCH_EXECUTION_NOT_INSTALLED，UI明确未接执行；不添加仅返回501的start占位路由。P5接入真实准入时再实现start及未确认拒绝。

### 3. 原生受控研究循环

使用明确注册的研究native组件，经ApplicationRuns准入。用户约定绑定project scope，round allocation使用 `LocalBudgetScopes`，每轮绑定实际root/plan，临时实验child使用 `DelegationService`。模型依照实际输出选择继续/换路线/结束，不由fixture固定步骤；约定已满足可直接停止。应用领域工具只提交研究意图与读写证据，实际模型、工具和remote执行走现有绑定/guard/usage机制，不直连provider或SSH。

应用依赖少量具体composition适配函数将当前原run身份传给core已有预算/delegation服务；不将core Store整体交给模型工具或HTTP请求。现有public context不直接暴露预算/delegation，任务2.1必须先验证最小接入：取原context身份→分配scope额度→绑定原plan/root→child准入/取消→读取原receipt。若当前服务签名不足，先由core变更补明确port和spec，不能在应用私下维护第二执行链。

原生恢复负责继续/核对原任务。应用重启可从事件和原receipt重建研究视图，但视图缺失不是重新submit许可。该区分比另建后台研究轮询worker简单且保留UNKNOWN边界。

### P5 首切片：确认的首轮准入与原请求引用

agreement.execution 显式包含 applicationRef（精确发布版本）、mode、materialChoices/connectionRefs、deadline（UTC epoch秒）及 perRoundCaps（rounds固定1）；这些字段随目标版本确认，缺少配置时start返回409。budget是整个项目承诺，perRoundCaps不得超过总承诺且计费类型/币种一致。不得从resourceRefs字符串猜测模型或连接。截止时间与额度不由服务器暗定。

首root的goal明确拼接完整「研究目标」「评价标准」「停止条件」三段，不仅传objective，不截断。组合文本受既有ApplicationStart的2000字符限制，超限明确拒绝并要求缩短约定。当前发布mode无inputSchema则直接传goal；有schema时只接受字符串goal且无其他必填字段，并按schema验证后传inputValues.goal。任何不兼容模式明确拒绝，不创建通用字段映射器。

每一轮是一个native root，对应一个scope allocation；临时child继承该root及预算，不单独bind_root。项目只创建一个scope；修订目标不得修改或重置已建立的总预算、deadline。首切片只准入第一个原root，不开放未经验证的后继轮入口。实验节点保存假设/条件，运行引用保存goal版本、原application request、allocation；task/run与执行状态始终读取core原回执。后续自主决策复用原生运行与选定材料；具体Workflow接入需先完成最小core契约设计，不手写provider循环，也不假定NativeWorkflows已支持Loop。

POST `/projects/{id}/start` 只接收requestId/expectedVersion。短事务按core admission锁→应用namespace锁→content namespace锁→usage锁顺序验证已确认版本，原子创建项目scope、实验/运行意图、allocation及factory原request→allocation绑定，提交后才await ApplicationRuns.start。所有core reserve入口均强制该绑定，不能通过另一个无allocation参数的路由绕过。已有task回执必须与公开scope inspect的原allocation.taskId一致，不匹配明确拒绝。重复请求只核对同一原request；已存在task（包括UNKNOWN）不重新调用start。尚无task时仅沿原请求恢复既有core准入，不生成新身份。首切片新request不能绕过已有实验意图启动第二root。GET `/projects/{id}/experiments` 返回领域事实及原回执投影，不把accepted当completed。P6当前切片在同一事务自动发布团队可读的精选开始快照，明确标为pending_admission；21907c3尚未写P3 outbox或终态记录，不能把内容发布视为事件已交付。

应用通过public.install注入ApplicationRuns与LocalBudgetScopes实例，不从公开context取出Store调用私有执行器。end在同一领域事务取消已建立scope，阻断未准入/后续工具模型入口；不声称中断已在途外部操作。旧目标原请求已确认的意图可按旧约定结束，修订创建的新目标没有自动启动权；首切片没有冲突后继。结束后的未准入意图不得恢复执行。UNKNOWN不释放预算。P5首切片不是自主多轮或C/D验收完成。

### P5 固定研究 Workflow consumer（21907c3 上的设计，尚未实现）

本节替换先前探索方案。应用工作树基线为P6 `21907c3d298b929a14362fb1477abcb0a07bd8bf`；通用child/custody桥接使用独立core变更`bind-delegated-workflow-operations`（本地`f953118`及其后续review整改）作为待合入依赖，不把其代码复制进应用。PR111的完成事务、P3事件与P6开始记录分别验收，不因为存在接口就宣布自主研究完成。

#### 固定组件与首切片的兼容边界

只安装一个应用拥有的固定`research-round` Workflow revision，发布应用中的`research`模式精确引用其nativeComponent pin，`experiment`模式使用既有factory-executor。两模式复用用户明确选择的模型/连接，child材料与工具是root已确认材料的子集；本切片不让模型替换owner、mode、provider、request、预算或资源引用。root的模型Step仍tool-free，实验工具仅供受治理child使用。当前最小方案使用同一选定模型，不预设多专家模型路由。

显式research deployment在core构造前创建具体ResearchWorkflow对象及NativeWorkflowRegistration/AdapterRegistration；install时将确定的ResearchRuns、记录服务、OperationCustody.start及WorkflowControl绑定到这个对象。具体签名为`ResearchWorkflow()`提供registration/tool_registrations；`research.public.install(state, *, workflow=None)`在core创建后构造ResearchRounds并一次性workflow.bind(rounds)。deployment仅追加Settings现有注册列表并用ApplicationAssembly的install闭包接线，无新增Assembly字段、第二lifespan或worker。只是当前消费者的静态装配，不新增插件工厂/服务容器。注册前不能执行，重复绑定拒绝。core默认入口无研究registration、seed或引用。

ApplicationRuntimeRegistry只按这个精确nativeComponent pin附加research owner并声明finalizes=True，保留其他binding/effect owner。第一治理Step仍要求匹配项目原intent或P3原delivery；用户直接发布使用此pin的应用不因此获得项目执行授权，缺绑定时在任何child/tool副作用前拒绝。该pin下未绑定的失败root可以按原技术失败完成，不把缺研究intent变成永久finalizing。

P5首切片允许任意已发布应用；这些已有task/plan/record继续只读观察，不登记为research finalizer、不修改其原applicationRef、不重新执行。新自主启动要求已确认execution.applicationRef/mode确实引用固定研究组件，且公开明确模型/连接与支持的自动轮次；旧配置需要新目标版本明确确认，不能把原用户选定app偷偷换成研究Workflow。已有首切片项目不能在原UNKNOWN未止时新开冲突root。

#### 每轮拓扑与最小领域数据

| 顺序 | 现有native primitive | 应用行为与证据 |
| --- | --- | --- |
| 1 | 受治理Function `research_context` | 校验原run/plan及研究intent或delivery；读取冻结目标objective/evaluation/stopConditions、原预算、前轮公开事实及来源版本，输出完整且有界上下文。P3消息文本仅是contentId通知，不能将通知正文当研究目标 |
| 2 | tool-free Agent `research_decide` | 选定模型返回严格结构化`stop`或`experiment`：可见理由、来源ID；实验分支含假设、条件和goal，停止分支含met/not_met及证据。无实验必要时直接停止，不强迫做一轮 |
| 3 | Router | 只解析上述结构化决定选择固定分支；不调用provider，不自动修补无效答案，不执行模型提供的代码/路由名 |
| 4a | 受治理Function `research_stop` | 持久本轮停止决定及证据等级，留给原完成事务收尾 |
| 4b | 受治理Function `research_launch` | 同事务创建/引用实验节点、具体运行引用及精选进行中记录；提交后以原RunContext调用唯一custody.start、固定step/effectSlot/adapter pin，inputs仅goal与固定experiment模式 |
| 5b | Agent + 既有factory_wait_operations | 等待原operation；由既有WorkflowControl恢复原requirement。未确认停止/结果时不进入下一实验 |
| 6b | 受治理Function `research_results` → tool-free Agent `research_evaluate` | Function从原custody读取已闭合的真实child结果及原约定，不信任wait模型的复述；evaluate接收这些指标/产物引用和原标准后决定continue/stop，并说明证据适用条件；进程completed不等于科学met |
| 7b | 受治理Function `research_record_decision` | 校验结果引用属于本轮原operation，保存决定，不直接启动后继、不分配下一root预算 |

决定只记录可见理由，不记录隐藏思维链。模型的met/not_met属于带来源的agent判断；可核对指标是事实，独立验证等级不能由模型自评升级。不引入评价DSL或假定一段自由文本标准可被框架自动证明。无效结构化输出、缺来源或技术失败留下明确失败事实，不强制固定次数重试；UNKNOWN只观察原操作。工具实际结果超出既有RuntimeObservation的inert/大小边界时必须通过原artifact引用读取，不截断后假称完整证据。

增加一个具体`research_rounds`关联：project/goalVersion、scope/allocation、原request/delivery（唯一）、冻结前轮记录ID、本轮决定、终态记录/后继event引用。round是有界root推理，不等于实验；立即停止的round没有虚构实验。实验节点保留假设/条件，attempt引用child原operation/task/run；同一假设可有多个实际运行。解除现有experiments.project_id与attempts.experiment_id的单值限制需显式非破坏schema迁移，保留旧行和旧ID；不要通过metadata.create_all假装旧库已迁移。原task状态始终由core投影，应用字段不控制native进度。

#### 原身份、等待与下一轮准入

治理Function直接接收native_workflows._wrap已验证的RunContext，不新增ApplicationExecutionContext.start_operation或rawStore暴露。核心固定DELEGATED_OPERATION_PIN拥有原operation→child唯一映射、保留request namespace、同root锁的子树停止证明及撤权cleanup；应用不调用DelegationService.create自行补派。每root一个scope allocation，child继承root预算，不能另allocate/bind_root。

research owner的observe_waits仅观察原operation并在闭合后沿唯一原requirement提交确定性reconcile命令；未闭合不提交命令，重复tick/重启核对原receipt，不生成新command/request。模型权利撤回则只由core清理，不继续推理。应用不设置自己的timer/worker、provider while、普通Agent等待恢复器或消息恢复循环。

首轮仍走确认后的ResearchRuns.start。其结束callback只对模型已保存的continue决定产生一个自定向P3事件；后继delivery由P3分配allocation并准入唯一root。下一root的research_context按可信原request→delivery→allocation→task及content源核对并关联round，不再次allocate或start。不能通过普通peer消息给研究执行端点发送看似contentId的文字来启动训练；缺P3 delivery或已确认首轮intent，第一治理Step必须拒绝。项目自己的execution endpoint与长期助手QA endpoint分开；每项目订阅只有自己这个接收者，不广播。

已选core窄只读接点为`AssistantEvents.delivery_for_task(owner, task_id)`：无原delivery时返回None，否则返回`{contentId,eventId,deliveryId,rootId,depth,scopeId,allocationId}`。core按原task.request_id→scopes.request_delivery→delivery/allocation/task核对；不create、不重新allocate/start、不授内容权限。应用另调用content.read(owner, contentId)核对研究project/goal/来源；deadline和execution endpoint来自本项目已冻结配置，不增加返回字段、不读core私有表。ApplicationStart的goal仍保持P3原通知文本，完整约定由研究步骤读取；不能修改已验plan来伪装直接启动。拒绝原因仅传播core有限已知结构化大写code/状态，未知异常用固定安全code，不存provider任意detail。接口及非研究fixture由独立core变更交付，应用只集成已提交版本。

#### 原完成事务与可观察停止

只使用PR111的`finalization_context(conn,task) → yield callback`。进入时取得research/content/event namespace锁；root→admission→上述namespace→usage锁顺序保持不变。core写全group terminal、settle scope；HELD回滚完成，原observer以后重查。callback核对持久决定并原子写本轮终态、精选content、至多一个后继event；错误回滚terminal/storage/reclaimed，不能新建usage通知表、独立finalize worker或在callback await/submit。

native技术失败、取消、拒绝或缺最终模型决定时保存原事实，不包装成科学met。成功决定且scope仍可准入、项目仍ready、目标版本兼容才可发后继；已结束/撤权/预算或deadline用尽明确记录无后继理由。作者已撤权时仍持久原领域终态和原证据引用，分享发布标authorization_withdrawn，不冒作者当前权限发布、不让content.publish拒绝永久卡住已停止group。预期业务边界与程序故障分开：过期/已取消不再emit；未预期内容/事务错误照常回滚，不广泛catch后假成功。

原已停事实不会被后来scope过期改写成失败。P3后继在事件提交后可能因当前权限/额度变化被拒绝：项目详情应投影该原event/delivery的blocked原因与原终态，不能显示仍在运行、伪造成功或另开事件根。delivery UNKNOWN仍保留原预算和身份。

#### 有限事件lineage与项目承诺

当前`EventSubscription.maxDepth<=20`，首个手动root完成后round2事件depth0，round22为depth20；即使项目预算更多，round23也会被传播上限拒绝。此限制不是用户的科学停止条件。不得悄悄把预算rounds截成22、reset lineage、另开同一自动链的root事件，或要求每若干轮重新审批来伪称已完成自主旅程。

已选core前置移除独立20硬上限：接收者配置非负maxDepth，lineage逐次递增；实际轮数由同一scope预算、每delivery caps.rounds=1和TTL分别执行，maxCandidates=20与现有fanout上限不变。研究自定向订阅才按总rounds推导depth（总rounds至少2时为rounds-2）；该公式不进入core，普通QA订阅仍可保持原20配置。非研究fixture须证明depth>20仍在scope额度处截止、原20配置语义不变、无重置lineage。该依赖尚未集成前，preflight明确阻塞无法兑现的自动轮数承诺，不静默截断、不将技术上限记科学not_met。

预算剩余不足一轮、deadline到达或用户停止时不发新event，保留实际已用额度、停止理由和可继续成果引用。目标修订也不重置scope或事件lineage；确认新版本前无新自动轮，新版本与在途操作的继续/停止说明沿A07执行。新的原始研究约定才建立新scope，不把技术暂停变成隐式新预算。 修订已确认且旧轮已终态时，显式start命令只在原scope和上一终态记录/parent delivery lineage内产生一次去重后继事件，不直接allocate或submit；旧轮未终态则保留原attempt。当前执行配置固定首次选定的application/mode/materialChoices/connectionRefs/perRoundCaps及endpoint，目标修订不能暗换执行配置，变更执行配置需后续明确迁移设计。总rounds=1不建立后继订阅且不生成后继事件。

#### P7/P8接点与本轮验收边界

P7之后使用团队记录ID/版本/适用条件检索和自己的分析内容，QA端点工具白名单不含research_launch/child/GPU；QA预算不借研究项目scope。该设计只保留读取来源、发布精选记录、事件ID及明确分离的endpoint，不顺手实现搜索框架/向量库/泛化消息路由。P8由本轮原证据/产物构建可复现manifest，留待独立实现下载、归档验证和另一成员复现，不把一个停止报告当成果包完成。

验收复用A03/A04/A06/A07：两种不同实际工具输出使同一模型fixture产生不同分支；已满足目标直接stop且零child；真实native暂停/重启/原reconcile、撤权后原cleanup、HELD完成回滚与原tick恢复；callback仅一个精选终态/后继event，后继只一个allocation/task；普通peer消息零child；目标变更不重置预算、跨20深度边界明确验证。A01验证卸载研究仍启动core。固定fixture仅证明机制，C01真实模型任务/预算及D01目标GPU未冻结时继续BLOCKED，不声称科研自主或生产容量通过。每个实现单元仍由作者之外完整base/head精简审查后进入集成。

### 4. 目标修订与停止

用户提交目标修改附当前版本；冲突返回当前版本，不最后写入覆盖。修改先形成新约定与影响说明，明确后生效。默认允许已在途的不冲突操作按旧目标完结并标为旧版证据；与新目标冲突的操作请求原身份取消，正向停止证明到达前不启动冲突后继。目标修订不重置scope消费；需要增加预算是另一次明确资源约定，不隐式扩容。整体停止仅阻止新尝试；UNKNOWN和子任务清理继续显示待核对，不要求伪造清理完成才能保存研究结束理由。

### 5. 自动记录与限定共享

P6可先独立交付开始记录：在首轮root intent、scope/allocation及原request绑定的同一事务，发布精选开始快照并在有明确相关接收端点时写既有P3 outbox；无接收者不补全员广播。快照区分“意图已记录/待准入”和实际已运行，不把创建内容当native成功；只包含明确共享的目标、条件和证据引用，不复制原聊天/连接秘密。PG验证事务失败全部回滚、同请求只有一个开始记录、双用户团队读作者写。此切片不宣称终态记录已接通。

PR110允许用户选择任意符合输入契约的已发布应用，用于验证首root机制；不能把这些app注册成research runtime owner，也不能将其原生成功包装成科学结论。固定研究Workflow经明确注册并取得精确pin后，才启用研究finalization_context consumer和终态/后继记录；其前可准备结构与接口测试，不注册临时catch-all consumer。后续新研究项目以该固定研究组件为执行契约，旧首轮切片的原task继续按其原计划观察，不重写或重新执行。

实验开始事务保存领域记录并产生通用事件；运行完成后从core原输出追加记录修订。记录包含作者、项目/goal版本、实验条件、运行/产物引用、观察事实与agent解释；不把LLM自评当验证。产物字节仍归core，应用只确定哪些条件/证据/结论进入共享视图。科学验证来自预先声明评价标准与实际指标；未知结果不填成零分或失败。

P6需要core限定内容读取契约：当前成员读取已发布的精确artifact引用，不能冒充作者打开全job；撤权和禁用实时生效。应用用core权限判定共享读/作者写，不建立自己的成员目录/ACL。没有此port前只能实现本人记录和纯数据投影，禁止以跨owner store读取替代团队证据API。应用事务和通用outbox原子性由P3确认，不能假定两个service调用天然原子。

### 6. 离线问答与定向关联

使用独立的研究问答native组件与端点，tool集合只有当前授权的记录检索和答复写入，不注册训练、GPU分配或实验提交工具；通过实际guard/dispatch计数证明限制，提示词只是行为说明。该端点使用接收者自己的模型/预算，不接受发送者替换连接或执行模式。引用材料中的指令视作内容，不成为工具权限。

应用选择少数相关端点及来源，通用P3负责事件订阅、投递去重和预算边界；不用全员广播兜底，不建专用mailbox轮询链。关联属于分析作者的新记录，引用原作者版本和条件；不得覆盖原文。以source→decision→action及相关/无关/过时负对照验证价值，不以消息数为收益。通知频率仍可按冻结策略配置，不能虚构已批准的全局偏好。

### 7. 成果与中文UI

2026-10-25 10:49新增用户门槛：研究UI后续扩展、定稿与含UI变更的合并暂停。必须先研究优秀真实产品设计、交付用户可见低/高保真原型，获得用户确认后按视觉目标实现。PR108临时功能界面已于收到指令前合并，保留且不回滚；功能测试通过不代表视觉确认。不得沿用旧Research UI作为定稿。底座、后端和非UI契约测试独立继续，不受视觉方案等待阻塞。

最终manifest链接原代码commit、依赖锁、命令、数据位置/hash、非秘密配置、运行证据、指标、负结果和剩余问题；归档核验先于远端清理。生成报告不能代替独立复现。另一成员不看原聊天按包执行，确定性输出精确核对，随机/GPU容差须事前冻结。

主界面为自己的助手与项目概览，详情按目标/实验与运行/证据/协作/成果下钻；复用core登录、导航、资源配置，不另造账户页。支持空状态、直接URL/刷新、退出重登、任务未知与清理提示；无旧研究页面残留。无需为该应用重做全站设计系统。

P4写入在发送前按当前owner及project/new保存原action/body/requestId到本地sessionStorage；408、网络错误及5xx保持未确认，重载后只允许用户显式按原请求重试，不自动提交。成功或首次请求确定拒绝才清除；已不确定原请求的后续401仍保留身份。仅保存本次非凭据输入，不跨owner恢复，不扩成通用执行恢复器。

### 8. P4显式装配入口

Python新增deployment的research组合入口，调用既有ApplicationAssembly安装research.public；默认agent-factory入口不安装应用。发行wheel可包含应用包，但standalone core安装仍不包含它。Web复用Workspace与核心Pages，通过独立research-composition/research-main静态入口注册研究目录卡和project URL；Vite显式research mode选择该入口，默认构建不导入研究应用。架构checker登记research拥有边界与两个显式composition roots，测试发现纳入应用目录；不增加动态插件发现或第二身份系统。

## Risks / Trade-offs

- [部分接入能力仍为待CI的stacked Draft] → 按下表接入门槛推进，依赖未过不写伪实现或临时跨权限通道。
- [实际模型未必得到科研提升] → 验收实际输出后的有据决策/停止/复现，固定oracle与样本，失败保留；不要求每次指标改善。
- [真实GPU/身份/容量未提供] → 确定性与本地浏览器先验收，C/D保持BLOCKED/NOTRUN；20人负载不由账号数或云端配置外推。
- [未知外部操作长期占用] → 保留原身份与预算，显式呈现，不用补偿重派让页面变绿。

## Migration Plan

1. P4新应用包、个人项目/约定与可选主页，不开启团队自动执行；先证明移除应用仍可用core。
2. P5接入native预算/child/remote，先合成机制测试再授权真实资源验收。
3. P6依赖限定内容共享port，发布自动研究记录；P7依赖P2/P3实现问答/关联。
4. P8成果与独立复现；P9完整17项验收、独立精简review、精确head检查。回退仅撤装配和新入口，不删除用户数据或原操作记录。

| 接入项 | 当前事实 | 开始依赖实现前需完成的可检查契约 |
| --- | --- | --- |
| P1端点/P2消息 | PR105/106已合入main | 复用现有固定端点与原消息/task身份，研究QA/自动执行各自限定mode与工具，不把底座验证外推成研究旅程通过 |
| P3事件/自动预算 | PR109为待CI的stacked Draft，尚非main | 合并前核对精确head CI/独立review；接入验证同事务outbox、receiver预算/TTL及UNKNOWN不重派 |
| 限定产物共享 | PR107已合入main | 使用ApplicationContent精选快照与精确artifact授权；研究记录需自身验收，不代理全job读取 |
| 首轮预算/准入 | PR110为待CI的stacked Draft，尚非main | 首轮可选用户发布应用只证明真实原root准入，不等于固定研究Workflow或自主科研 |
| 完成事务 | PR111/f25c899已本地实现并通过所报PG/review，仍为待CI的stacked Draft，尚非main | 固定研究Workflow pin后才能注册finalizes=True；精确head CI仍须跟进 |
| child/custody | 独立core变更bind-delegated-workflow-operations已本地实现（f953118及review整改），未包含在本应用基线 | 集成精确review/检查通过版本后复用固定pin；不复制adapter或cleanup；真实本地机制不代表远端GPU |

## Open Questions

正式研究任务/模型参数、调用预算、GPU主机及数据、科学容差和代表性容量负载待正式run前冻结；不阻塞上述确定性实现。额外评论/复核/分支、原始数据或私聊共享不在已确认范围内，默认不开放；若以后提出，另更新规范。没有将这些未知项包装为本次已验收能力。
