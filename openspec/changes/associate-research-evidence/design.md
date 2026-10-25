# Design

## Context

基线`76fc1c3`。上位契约为`docs/plans/research-platform-acceptance-contract.md`：A08要求相关范围/去重/当前授权；A02/A03保留身份与权限；A05/A07保留原执行与预算；B02真实双用户旅程；C02必须有source→decision→实际action，C03必须有真正有用关联，不能全部沉默或消息数取巧。正式真实任务/模型/预算/rubric尚未冻结。

已核对源码：

- `research/records.py::start`和`rounds.py::_finalize`发布精选team事实；后者目前只发自定向`round.continue`，不能把它改成同事消息。
- `AssistantEvents.emit`要求调用方当前领域事务和作者自己的contentId；`delivery_for_task`核对原task/request/allocation返回7个opaque引用。`event`给作者安全状态。现有deliver_batch负责原准入/恢复，无需新增后台进程。
- `ResearchQA.context`只接受原message/task/config，保存全部实际输入依赖；普通问题的答案由core reply拥有，tool-free模型不运行实验。
- `ResearchRounds.context/record_decision`当前允许前轮原发布及本轮原operation，不接受任意同事证据。新的来源只应在实际consumer用到时增加。
- `ApplicationContent`没有派生来源依赖传播。若把同事证据影响的分析直接复制进普通team publication，原来源撤回不会自动隐藏这份新正文；必须避免这种无依赖复制。

## Goals / Non-Goals

**Goals:** 研究事件触发有限检索与少数相关助手联系；自动生成有出处的agent分析；所有新共享分析读权逐源复用core；实际已确认研究可在下一决策边界使用适用证据，并记录原动作；有明确不相关/过时/耗尽/撤权状态。

**Non-Goals:** 新A2A协议、向量库、通用通知框架、第二worker/恢复器、ACL/vault或余额管理。Peer QA/关联不得启动GPU，不能因收到关联自动建立新研究。BYOK仅操作额度，token/费用未计量；本规范不解除硬费用验收，不改真实C/D门槛。

## Decisions

### 1. Resource configuration enables automatic association processing

在原`POST /assistants/me/configurations`的首次助手资源与有限预算确认body中增加`associations:{enabled:boolean,maxRecipients:int}`。正常完整研究旅程的配置界面应默认展示启用主动关联及共同操作额度，并将启用值显式提交；一旦配置成功，有关研究事件自动检索、发送和记录，不再逐条审批、手动发布或等待用户在线。owner可明确停用此能力。服务端不得把旧的仅私问配置默认为新增自动消费授权：旧行缺字段时显示“需完成研究助手资源配置”，这属于迁移/资源未配置状态，不能作为已完成完整旅程或A08的全沉默PASS。变更走已有expectedRevision CAS和原收据。新配置仍明确模型、个人连接、finite rounds/toolCalls/deadline，token/amount/currency必须null，继续展示现有非计费notice。

发出者未明确启用关联时不自动发事件，记录disabled状态；接收者也必须有有效订阅。启用时在相同配置事务为**同一个QA endpoint和同一个scope**创建`namespace='research',eventType='evidence.available'`订阅（接收侧maxCandidates沿core上界20，发送侧maxRecipients决定实际小集合）；停用/替换沿原endpoint停用使旧订阅不能新准入，不迁移旧task。maxRecipients默认2、owner可在1至core20界内明确选择；它是技术fanout设置，不是C质量阈值。实际运行前冻结该配置，不能为得到回复自动扩大候选。事件maxDepth=0：关联不发后继关联；现有round.continue预算/lineage不受更改。

### 2. Trigger and deterministic candidate selection

仅新发布的`research.experiment.start`、`research.round.terminal`精选事实触发；普通私问、关联分析、重复读和旧记录扫描不发事件。start仍如实pending/in-progress，terminal保留科学负结果与技术失败区别。

在原publish事务中调用应用`prepare_associations(conn,owner,content_id,request_id)`，直接复用`events.emit`，不await模型/网络。对当前作者可读team原研究记录取有界窗口50条，排除本记录、本人记录和派生association；不读私有项目标题/工作区或原任务日志。候选记录若有派生依赖，必须先走第4节受控读取，不能从普通content壳绕过依赖读取关键词。仅使用当前有权读取的objective、conditions及experiment.hypothesis/conditions字段匹配：Unicode NFKC后casefold，字母/数字连续词长度至少3，连续汉字取双字片段；排除固定通用词research、experiment、result、study、研究、实验、结果、数据、模型。按不同有效词交集数量降序；此规则随规范固定，不根据隐藏oracle或任务答案选词。无有效词交集即不候选；同作者多个匹配只保留最高分，按分数及稳定record id打破同分。

只选择匹配原记录作者的稳定助手，并检查其启用关联、当前配置和双方对触发/匹配记录的core.read；取作者配置上限内的少数目标。无匹配/无可用助手/额度不足不广播兜底。纯词项筛选只用于降低fanout，不宣称科学适用性：条件不同/过时证据由后续模型明确区分，C03另验质量。

应用持久化一个`research_association_intents`记录，唯一触发contentId，保存原eventId、候选endpoint及匹配contentIds/规则版本/分数（不复制正文）。同事务写P3 outbox；无候选也保留空选择结果以避免重投重新扩大范围。使用原owner命令键，发布/关联意图/outbox一起回滚。锁序沿现有root→admission→research/content/event/endpoint namespace→usage，候选读取不引入反向锁。

### 3. Event input is a bounded branch of the existing QA consumer

不新增助手身份/执行endpoint。原QA context若`delivery_for_task`非空，只接受本应用association intent的精确eventId、原endpoint、原message及触发contentId；不凭模型text中的id选项目或来源。无匹配原intent拒绝，普通私问继续现路径。

输入强制包含原触发记录与匹配记录，其他来源仍受当前双方team read交集、最多8条/16KiB边界。不能因字节限制静默丢掉触发或匹配对；必要输入超限则记录明确拒绝，不发无依据模型调用。原task重入使用原完整input依赖集合，重新鉴权、不重选。保存原配置、event/delivery/task及完整input IDs，并合并每项派生输入的完整原来源依赖；模型不能缩减。显示/上下文的8条与16KiB上限不允许截断持久依赖集：已读取的关联或前轮输出即使只显示一个引用，也携带它所有原来源。必要输入无法在边界内安全提供时明确停止本次新消费，不用截断依赖继续。

仍三个顶层native步骤、tool-free owner模型和严格JSON文本校验。事件分支输出增加`relation:related|conditions_differ|not_related`、`applicability`说明；至少引用触发与一条实际匹配来源才可产生关联。`not_related`原任务正常完成但不创建用户通知；存有界原outcome以去重，不用其作为C03质量通过证据。普通私问不需要relation字段且仍只调用core.reply_for_task；它不自动变团队记录。

事件分支只创建**领域关联**，不把相同回答再写core reply，不反向send。`research_associations`按原delivery唯一，保存作者、原task、触发/匹配、完整input依赖、agent_analysis正文、适用性和原时间。它不是普通私问答案表，也不持有分享开关/ACL。不会emit新的关联事件，因而没有自动聊天风暴或派生循环。新fixed component pin需显式setup发布/配置，不能改旧plan身份。

### 4. Every peer-influenced field remains source-dependent

`GET /associations`与`GET /associations/{id}`对当前actor及原作者检查membership，并逐一调用core ApplicationContent.read验证**全部实际input依赖**。任一来源不可读则整个分析/引用不返回，不能只删链接。列表省略不可读项，直接URL404并由UI说明来源当前不可访问；不得通过错误详情泄露被隐藏的来源id/正文。旧来源重新共享也不新增分析或任务。

保护对象不是只有reason/sourceAssessments。只要某个模型/child实际接触了peer输入或派生输入，该作用域产生/复制的hypothesis、conditions、decision.goal、结论/outcome、项目ending原因、child文本/结果/产物、输出标签与文件名等均可能携带来源信息，全部受其完整依赖集约束。不能因为字段被执行过、由child返回、被称为“实验事实”或复制到新版本，就自动脱离来源保护。

普通team ApplicationContent只能保存明确allowlist的opaque记录/任务/操作ID、固定runtime状态、固定pending/ended标签和受控derivationRef；不保存上述文本、科学outcome、任意metadata、artifact引用/名称或模型生成标题。原事实页和事件consumer下钻应用受控读取后，才可取得完整派生字段。start/terminal/实验详情/project ending/关联list和detail均使用同一实际依赖判断，不能通过搜索摘要、错误详情或导出绕过。新派生child产物不自动经原artifact发布接口获得team可读权；未来P8共享/导出仍必须检查完整依赖，当前不为此新增通用artifact授权。

关联不是事实验证，不覆写他人的记录。既有原native任务私有审计保留原owner身份，不新增向同事的任务读取权；不声称可追回此前已读内容或已提交给模型的输入。撤回阻止新的应用共享读取及新消费，不能删除原运行身份、预算或停止/清理事实。

若关联创建或读取期间来源撤回，短事务沿core admission锁序重读依赖；模型await不持锁。record时权限失败不发布分析；原runtime/预算仍由core收尾，不另起recovery或新task。未知基础设施错误不得吞成“不相关”。

### 5. Only actual research consumers gain peer-evidence dependencies

在**已确认、已准入**研究root的context边界，用同一有界检索规则读取当前owner可见原team研究记录；可附带当前可读关联分析作为导航，但最终依赖始终包含原事实来源，禁止只喂同事LLM总结。peer来源最多8条，原本无peer来源的轮次保持既有结构和路径，不普遍改写全部decision。

有peer输入或继承了peer派生输出时存`research_round_peer_inputs`（原round id及去重后的完整原来源content ids）。依赖采用限定于该研究consumer的平面集合：本轮集合=前轮实际读取输出携带的集合∪本轮实际读取关联携带的集合∪本轮新读取来源（包括其已保存集合）。通过原round/operation/association绑定取集合，不能由模型或客户端声明“无依赖”。保存直接可审的原input引用与该并集，不建通用递归DAG。

并集随原child、terminal、后继round及目标修订后沿用的旧结果传递；记录换id、压缩成摘要、模型未引用某来源、目标revision增加，都不能清掉原依赖。保留完整并集与有界模型显示窗口是不同职责；不截断集合为“最近8条”。无任何peer输入/继承输出的历史轮次仍走原路径。Decision/Evaluation仅为这些轮次提供`sourceAssessments:[{contentId,disposition:use|reproduce|not_applicable,reason}]`；使用或引用必须来自实际input，解释适用条件，可有理由独立复现，不强迫每轮复用。该选择与原实验hypothesis/conditions/goal及原operationId一起保存，形成可核对source→decision→action；仅引用或自称复用不能满足C02。

launch前重新验证全部peer依赖及原goal/version/预算；来源撤回阻止**新**动作，不抹去原child/UNKNOWN效果或妨碍原身份观察取消。已有结果仍由原finalizer记录。所有实际受peer输入或其后继输出影响的字段按第4节保护；team start/terminal仅共享safe opaque IDs/固定状态和derivationRef，绝不把hypothesis/conditions/goal/child output重新标成无依赖事实。owner项目/ending/experiment/round API也逐源检查后才返回这些新派生字段。撤回后仅原状态/identity仍可见；新round即使只读上轮摘要或原child结果，也必须继承并核对完整并集，不能借摘要洗掉来源。旧无peer输入的历史记录不批量重写。

不为新关联自动开始项目或触发GPU。运行中的项目只能在本来获准的下一round/launch决策边界消费证据；P3关联事件绝不路由到`round.continue`。任何原UNKNOWN不因收到新证据而重派。

### 6. Minimal HTTP and evidence

- 原配置接口增加明确association设置；owner view显示当前启用状态、操作额度与非计费notice，团队目录仍不暴露私有scope/连接。
- `GET /api/factory/research/associations?after=&limit=`：limit1–50，当前可读不可变关联及nextCursor；无分析项时真实空状态。
- `GET /api/factory/research/associations/{id}`：作者、agent_analysis、适用性、已授权来源与原记录链接；不提供编辑他人内容或自动启动接口。
- project/experiment原详情仅在实际使用peer来源时增加sourceAssessments和原action引用；不另造“采纳”按钮来伪造模型真实使用。

A08测确定性收件规则、无匹配零发送、重复/restart原event/message/task/allocation、耗尽/过期零新准入；A03用独特canary让模型复制进hypothesis/conditions/goal、child返回值/文件和ending，再撤回未被最终引用的原来源，逐一读取start/terminal/project ending/experiment/association及下一round context：安全壳只留IDs/固定状态，所有派生字段隐藏，新消费拒绝且原操作继续可核对；B02测真实两会话显示/刷新/来源撤回/不能改别人。C02用真实先导证据与同构任务有/无经验配对，保留无关/过时负对照，按事前rubric观察真实动作差异；C03要求有用关联，不能全沉默通过。合成模型只证明机制，正式费用/模型/硬件未冻结仍BLOCKED。

## Risks / Trade-offs

- 有界词项窗口会漏掉语义相近记录；明确显示检索范围，不引入未验证向量平台。是否够用由C03而非消息数决定。
- 同QA scope供私问和主动联系共用，自动联系可能先耗尽额度；配置需明确展示共同额度与截止，绝不自动续额。可调整显式配置而不重置原研究项目预算。
- 派生分析不能复制到普通content是当前core能力的真实边界；若未来要通用派生内容分享，须另立core规范，不在此偷偷加第二ACL。
- 需要独立审查event分支与私问分支的职责、发布原子锁序及源依赖读路径，确认没有过度通用化。审核通过后才开始产品实现。
