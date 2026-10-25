# Design

## Sources and ownership

源版本301811b。ResearchWorkflow注册仍由deployment负责，setup从当前store.native_workflows.pin('research-round')读取准确pin，工具列表以当前应用代码FUNCTION_TOOLS及factory_wait_operations为准，不固化旧hash。MaterialGovernance.create_draft/publish、ApplicationService.create_draft/publish拥有不可变内容、作者和发布规则。Store/治理事务拥有原命令收据；setup只组合这些能力。

候选来源：personal_models.list(owner)投影reference/provider/model/available及可选connectionRef；connections.list(owner)投影已有ref/registrationRef/kind/capabilities/available；store.materials(published_only=True)提供当前已发布实验tool材料；execution_bindings.describe()提供可用真实环境adapter描述。返回白名单字段，不返回凭据或连接句柄。输入必须使用actor已有绑定的connectionRef/ref，reference与registrationRef只是资源登记身份，不能代替执行alias。可见共享模型若尚无actor binding，必须引导现有显式绑定入口；GET不得偷偷bind。缺模型、环境或实验工具显示具体缺项，不能填demo/fixture适配器或虚构知识/环境材料。

## HTTP contract

前缀/api/factory/research/setup，所有操作使用当前认证成员，拒绝额外字段。

- GET /：{workflowPin, models, connections, environments, experimentMaterials}。读取不创建种子、不探测远端。experimentMaterials各项增加connectionRequirements（依赖闭包实际adapter的name/kind/requiredCapabilities）、available及缺项unavailableReason，让表单无需推测连接类型。
- POST /drafts：{requestId,name,modelConnectionRef,environment:{adapterId,revision,connectionRef?},experimentMaterialRefs:[{id,version,sha256}],connectionRefs:{slot:reference},budget:{toolCalls,maxDepth,maxChildren,operationSeconds,outputBytes}}。budget沿core v2规则。name与requestId沿既有长度。此操作仅保存本人setup intent与定义预览，不创建材料或应用版本、不发布、不运行。返回{id,state:'draft',applicationRef:null,connectionRefs,materialRefs:[],preview}；preview明确是待发布声明，不冒充真实应用pin。
- GET /{id}：owner读取setup当前状态及原引用。
- GET /requests/{requestId}：owner读取原prepare或publish收据；缺失返回404，不能据此换ID重做。
- POST /{id}/publish：{requestId}，这是成员明确发布确认。重新验证当前准确Workflow/adapter与资源权限后，单事务内创建并发布所需材料及应用；返回{id,state:'published',applicationRef,connectionRefs,materialRefs}。

UI先展示所选资源、实验工具和预算范围，成员点击“保存草稿”及“发布研究执行配置”；缺项链接现有模型/连接/材料入口。完成后把准确applicationRef、mode='research'、connectionRefs交给研究约定；个人deadline/perRoundCaps仍由约定填写。setup不创建项目、助手、预算scope或native任务。

## Definition construction

共享定义为contractVersion2，research模式包含当前nativeComponent pin和应用INPUT_SCHEMA，experiment模式使用既有native executor。二者使用同一owner-model材料（owner-chat-completions-v1，symbolic connectionName='model'）、一个真实environment材料、用户选择的实验工具及依赖；research另含当前固定研究控制工具。只生成真实应用控制材料和已注册adapter声明，不生成fixture compute/knowledge。实验工具必须是当前已发布且有runtimeBinding的tool；排除研究控制工具作为实验计算。依赖闭包和能力/工具集合由现有governance核对，不能盲复制fixture权限。

当前源版本尚未确认任何非测试environment注册；真实部署adapter是显式前置依赖，空候选阻断发布，setup自身不会创造环境。环境选择仅支持当前已注册且非demoOnly的environment adapter，config为空或仅symbolic connectionName='environment'。若该adapter需要额外配置，本slice明确拒绝并说明缺配置，不让用户贴JSON，也不伪称所有环境已支持。对应连接按descriptor kind/capabilities做core preflight。实验工具已有runtimeBinding的symbolic connectionName沿原声明使用；reserved model/environment槽不允许与不同kind冲突。模型使用既有个人或明确共享连接，setup不收密钥、不新建vault。

connectionRefs只存owner setup与返回给其执行配置；共享material/definition只存symbolic slots。Bob选择Alice已发布的同一applicationRef时，沿现有执行配置选自己的连接，材料hash保持相同，不为每个使用者克隆共享材料。

ApplicationService.create_draft会检查已发布材料闭包，所以prepare不能伪造可引用应用草稿，也不提前发布材料；仅显式publish时在同一事务内完成治理创建/发布。

## Atomicity and recovery

prepare将当时准确workflowPin保存在preview中；publish必须比较当前pin与该preview，变化则拒绝并要求重新查看、确认，不静默替换。prepare只存setup intent；publish将setup命令与材料/应用治理写入在同一Store事务内完成；外层setup namespace锁与既有governance锁次序固定。不跨此事务做网络/模型/环境副作用。相同owner/requestId同内容返回原结果，异内容409；发布重投不新建版本。请求丢响应后GET原收据或同ID同body重试，禁止用新ID兜底。只有成功提交的发布状态才标published；失败事务回滚，保留原失败运行证据。已返回的历史收据不是当前执行权限保证，执行准入仍由core实时检查。

## Acceptance and limits

确定性契约测试：无启动写入；非成员/跨owner拒绝；draft不创建治理版本或发布；明确publish后准确pin可读；相同请求恢复无新版本、异内容冲突；schema无连接ref或凭据；缺/撤销资源无新发布；不调用adapter factory。PG测试证明嵌套治理同事务回滚、重启原收据与并发原命令幂等。双用户同published app/material hash用个人连接做真实core preflight；合成凭据/本地adapter只证机制。Browser验收由集成方以空库走资源配置→setup表单→明确发布→研究约定，无JSON粘贴；未执行前保持NOTRUN。真实模型/GPU另验收，不由setup通过替代。
