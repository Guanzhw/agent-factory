# Design

## Context

基线3b467519；只写spec。事实依据：`applications/research/projects.py`现assistantId为core endpoint；`rounds.py::_prepare`为项目创建内部执行endpoint；`workflow.py`已采用顶层原生步骤，避免Agno 3.1嵌套wait恢复丢后续节点；`public.py`显式装配。`assistant_messages.py::message_for_task`返回原messageId/senderId/recipientId/endpointId/text并校验任务/预算关联；`assistant_endpoints.py::AutomaticBudget`引用接收者scope。`application_content.py`拥有当前内容读权；`execution_bindings.py::build`要求一个model和environment，EnvironmentLimits是已有纯本地边界数据契约。

独立core change提供`reply_for_task(receiver, task_id, text, content_ids=())`，没有HTTP写答案端点；原消息read返回reply投影。该依赖须review并集成后才实现QA提交，应用不复制答案存储或双方ACL。

## Goals / Non-Goals

**Goals:** 一个成员一个稳定研究助手身份；明确配置有限预算后可在浏览器离线时回答同事；仅用双方当前可读的团队研究记录；原问句与回答私有；恶意证据不能触发训练或获得额外工具。以现有setup/治理、消息、预算和native执行完整接线。

**Non-Goals:** 常驻PersonalAgent、跨应用总助手、私人记忆导入、GPU任务、自动增额、回复反向派发、通用插件/检索平台或新向量库。主动关联和研究经验转实际动作保留为后续可验任务，不以私问完成替代整个P7。视觉确认已解除，前端可按此接真实接口；C/D真实模型、任务、预算和硬件验收参数未冻结仍BLOCKED。

## Decisions

### Stable identity and historical compatibility

应用用GovernedStorage存`research_assistants(id, owner_id UNIQUE, configuration_revision, qa_endpoint_id)`及原owner命令收据；不可变`research_assistant_configurations(assistant_id,revision,endpoint_id UNIQUE)`保留旧配置归属以恢复原task，当前身份只指向最新revision。POST创建，GET不偷偷创建。相同owner并发不同命令也只得到一条稳定身份。持续身份不意味着常驻进程或24小时推理；native任务只在已授权消息触发时运行。

项目新增nullable `research_assistant_id`，HTTP为`researchAssistantId`，必须指向当前owner的稳定研究助手。旧`assistantId`/assistant_id仍为历史endpoint，不重解释、不覆写或根据字符串猜测迁移；旧行新列为null。新项目显式选择或通过owner助手发起时关联新字段，不要求先有task。每项目round endpoint继续内部持有，不作为助手目录中的个人身份。

配置修改采用expectedRevision CAS；新scope、endpoint、旧endpoint停用、不可变配置行与current指针在同一Store事务中完成，锁序admission→应用namespace→endpoint namespace→usage；失败整体回滚，不留有效孤立配置。每次显式新预算配置可创建替代QA endpoint并更新稳定assistant指向，旧endpoint停止接收新请求；原任务、旧scope和原消息/收据保持原身份，不迁移或自动重新准入。预算用尽/到期后报告不可用，等待owner重新配置；不存在隐式续费或无限scope。

### Fixed QA component and setup

新增固定`research-qa` Workflow，仅三个顶层步骤：受治理`research_qa_context` → tool-free选定模型 → 受治理`research_qa_record`。两个函数是可信静态executor，不作为模型可调用工具；模型tools=[]。精确pin、唯一QA mode与tool集合在配置时验证。不得带研究launch、delegation、CLI、MCP、remote或GPU工具/compute模式；拒绝任意用户app冒充QA组件。无外部操作/等待，不注册第二恢复器或自己的worker。

QA环境是应用显式注册的固定adapter，只返回已有EnvironmentLimits，无prepare、远程target、连接或外部执行。不能任选研究compute环境。core Budget当前maxChildren/maxDepth最小为1；不能写0伪称已有该能力。无训练能力来自完整固定组件/模式及可达工具集合，而非提示词或伪造零数值。实测模型恶意tool请求、伪造研究消息均零训练/GPU dispatch。

复用setup的owner草稿、明确publish、原子材料/应用治理及回执：新增窄`POST /api/factory/research/setup/qa/drafts`，body `{requestId,name,modelConnectionRef,budget}`，budget为现有core应用运行预算。环境和两个控制材料由已安装QA注册提供，不接受实验材料/环境/任意JSON。现有`GET /setup/{id}`、`GET /setup/requests/{requestId}`与`POST /setup/{id}/publish`处理此明确类型；preview及已发布结果增加`mode:'qa'`以供接线。内部复用治理流程，不引入purpose插件框架。发布只存符号model槽，个人连接留owner setup。

助手配置另显式选择上述published applicationRef与本人connectionRefs，并提交总scope caps、每问caps和deadline。每问caps.rounds=1，总rounds/工具调用有界；metered模型必须指定有限tokenLimit/amountMicros/currency，沿现有_caps规则校验，不能把未配置视作无限。模型/连接不能由应用自选provider，不能按“余额零”假定可免费调用。单纯保存/发布/配置不调用模型。

### Original inputs and dependency set

context用RunContext及`message_for_task(receiver,task)`取原问句/双方身份，核对它属于该稳定助手的一个已确认原QA配置，不能把模型输入sender/endpoint作为权限。无原消息或不相符原task在模型之前拒绝。旧配置原task恢复按其已保存endpoint关系核对，不能因新配置而重新绑定。

候选只从ApplicationContent分页读取当前团队研究记录，先限制visibility=team和source.application=research，再对每个候选分别以sender和recipient调用read。本人私有记录、原对话、vault、全job、未经精选原始产物不进入模型输入。初始实现限定一次候选窗口最多50条、上下文最多8条且总16KiB；以问句与已有标题/条件/结论可见文本的直接匹配选候选并稳定排序，未命中明确证据不足，不广播或无限扫描。此处是可测试资源边界，不是相关性质量通过阈值；多语言检索质量由C03另验，不为通过测试硬编码答案。模型不能自主调用检索或训练工具。

`research_qa_inputs`仅存原task/message/配置身份及实际输入contentIds，作为原输入依赖记录，不存另一份答案或权限表。先在同事务保存已选完整输入依赖集再给模型；原task重复context固定原集合并重新鉴权，不自动换证据。模型输出 `{answer, citations:[contentId], evidenceLevel:'agent_analysis'}`，answer符合core reply 2–2000字；citations只能来自原集合，可少于全部输入，也可在证据不足时为空。

关键：提交core的content_ids是模型实际接触的**全部输入依赖集**，由可信context记录读取，绝不是模型最终选择的citations。模型不能删依赖逃避撤回。结构化citations仅作subset校验，正文可包含有出处的文字引用；无需新增引用表或扩展core reply payload。客户端把core contentIds标为“输入依据”，不能冒充模型逐项明确引用，也不能减少core依赖集。无新增通用hash链。

### Reply and revocation

record调用独立core同步`reply_for_task(receiver,task_id,answer,content_ids=full_input_set)`；core原消息记录拥有唯一reply，同内容重投幂等，异内容拒绝。应用不反向send、不另建回答表、不创建团队content/event、不借对方taskId访问完整运行。

core原消息read返回`reply:null`、`{state:'available',text,contentIds,createdAt}`或`{state:'source_unavailable'}`。来源提交/读取与内容撤回共既有admission事务边界；任一实际输入来源撤回，对双方隐藏整个派生正文及引用，不能仅删链接。双方会员禁用沿现身份机制检查，不声称内容锁覆盖所有账户权限变更。context读取后的已发送模型输入、已读或下载内容无法撤销；不为保持锁而跨网络/模型await持锁。原问句按原双方权限保留，隐藏不是删除历史。

### Minimal application HTTP

所有写入使用现有requestId约束/owner原收据，额外字段拒绝。目录不暴露他人model连接、scope或endpoint。

| Method/path (`/api/factory/research`) | Input | Result / behavior |
| --- | --- | --- |
| GET `/assistants/me` | none | `{assistant:null}`或owner完整助手配置投影；不创建 |
| POST `/assistants` | `{requestId}` | 稳定`{id,ownerId,configurationRevision,qa:{state:'unconfigured'}}`；并发唯一 |
| GET `/assistants?after=&limit=` | 现有cursor，limit 1–50 | `{items:[{id,ownerId,displayName,qaAvailable}],nextCursor}`，只当前团队成员，无私有配置 |
| POST `/assistants/me/configurations` | `{requestId,expectedRevision,applicationRef,connectionRefs,budget:{caps,perQuestionCaps,deadline}}` | 同一assistant的新revision和QA可用状态；有限scope/当前端点归owner；不执行 |
| POST `/assistants/{id}/questions` | `{requestId,text}`，原core文本限制 | 解析当前QA endpoint并用当前sender调用core send，返回原message投影；不可调用他人私有原task |
| GET `/assistant-questions/{messageId}` | none | 直接投影core双方read，包括delivery和reply，不另设应用ACL |

项目create的`researchAssistantId`为可选新字段，read保留旧assistantId与新字段。未配置/到期/撤权使用可解释的blocked状态与core安全code，不抛provider正文；提问先以sender/requestId查core原request收据；存在时核对正文一致且原endpoint属于目标稳定助手的不可变历史配置，返回原message。只有明确原request不存在才解析当前endpoint并发送；其他assistant/异正文冲突，其他错误原样传播。发送UNKNOWN保留原message/request，只读/同ID恢复，不新建问题。QA问题不自动变团队研究记录。前端在已确认视觉方案中使用助手入口、显式setup/configuration、私有问答与来源状态，未配置时引导现有资源入口。

### Remaining P7 value path

后续任务沿原P3研究start/terminal事件，按当前读权/条件相关性选少数接收者；无相关目标不发，禁止全员兜底。关联记录属于分析作者，不覆盖别人；私问不自动共享。ResearchRounds.context/decision/launch继续记录来源适用条件、采用/拒绝理由和实际原操作，使source→decision→action可核验；允许有理由复现，不强制跳过或必然科研提升。不新增轮询器/向量数据库。该后续单元需先冻结具体关联规则spec，再实施，不把本QA切片当完整P7关闭。

## Risks / Trade-offs

- 私有reply是明确core依赖，未落地前不能用反向消息或app回答表兜底。
- 固定候选窗口限制覆盖面，需用户可见“证据不足/检索范围”而非伪称全库完备；C03判定相关性价值，不能仅按消息数。
- 非破坏迁移和配置更替必须实测历史assistantId/原任务不变；旧成员禁用不等于删除其记录。
- C02配对有/无经验和C03真实离线QA需事前冻结模型、任务、预算和rubric，oracle仅给评审者，不给被测模型。A类合成仅证明机制，D类远端/GPU/容量仍独立BLOCKED。
