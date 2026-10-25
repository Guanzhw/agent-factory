# Spec Delta

## Purpose

为每位成员提供持续身份的研究助手，利用现有受预算原生执行回答私有经验询问。问答只依据双方当前可读团队研究记录，保持出处、原任务身份和资源边界，并与项目内部实验端点、原消息权限及后续主动关联明确分离。

## ADDED Requirements

### Requirement: Stable member research identity
应用 SHALL 为每个owner最多保存一个稳定researchAssistantId，身份不代表常驻进程；替换QA配置不得改变该身份或迁移原消息任务。

#### Scenario: Concurrent creation and read-only lookup
- **WHEN** 同一成员并发创建或重投原命令，随后读取个人助手
- **THEN** 只有一个身份；GET本身不创建身份、endpoint、材料或native任务

#### Scenario: Existing projects and multiple execution endpoints
- **WHEN** 旧project.assistantId已有endpoint引用，新项目选择researchAssistantId并启动多个研究项目
- **THEN** 旧值含义和历史记录不变，新字段只接受owner助手；项目内部round端点不增加个人助手数量

### Requirement: Explicit finite QA configuration
应用 SHALL 通过现有明确发布流程配置固定QA组件、owner模型连接与有限scope/caps/deadline；不得默选provider、复用任意compute环境或自动续额。

#### Scenario: Unconfigured or exhausted assistant
- **WHEN** 助手未配置、预算到期/耗尽或资源撤权后收到新问题
- **THEN** 显示有界不可用原因，不创建无预算执行或自动新scope

#### Scenario: Owner replaces configuration
- **WHEN** owner以正确expectedRevision确认新配置
- **THEN** 稳定助手身份不变，新问题使用新endpoint，旧endpoint不接新请求；原任务/预算/收据保持原身份；并发旧revision拒绝

#### Scenario: QA setup publication
- **WHEN** 成员保存QA草稿并明确publish
- **THEN** 仅发布当前固定QA pin、两个治理函数及纯本地EnvironmentLimits声明；无实验工具、无运行、无凭据写入共享定义

### Requirement: Original private QA execution
QA SHALL 使用三个顶层native步骤和tool-free模型，从原message/task端口取输入；问句/答复仅沿core双方权限，不反向send或公开成团队记录。

#### Scenario: Forged question context
- **WHEN** 没有原消息的任务或模型提供伪造sender/receiver/task标识
- **THEN** 在模型执行/回答提交前拒绝，不能访问另一消息或派发实验

#### Scenario: Offline recipient and malicious evidence
- **WHEN** recipient退出浏览器，合法问题及包含要求训练/CLI/MCP/remote调用的来源进入受限QA
- **THEN** QA在原预算内回答或明确失败；实际训练/GPU/delegated-operation dispatch均为零，模型没有这些工具，问句与答复不创建团队content/event

### Requirement: Complete input dependency protection
QA SHALL 只向模型提供双方当前可读team研究记录的有限交集，并持久记录原task实际接触的全部contentIds。模型选择的显示引用不得缩减依赖集。

#### Scenario: Recipient private data and insufficient sources
- **WHEN** recipient拥有私有金丝雀、私聊或凭据，团队候选中没有满足边界的证据
- **THEN** 私有内容从未进入模型输入；回答明确证据不足，不编造引用或扩大检索/权限范围

#### Scenario: Uncited input source is withdrawn
- **WHEN** 模型读了A和B但答案仅显示引用A，B在提交前或读取前被撤回
- **THEN** core reply依赖仍包含A和B；提交拒绝或整个派生答案及引用不可用，不能只移除B链接后保留正文

#### Scenario: Original input context replay
- **WHEN** 原task重复读取QA context或重启恢复
- **THEN** 核对原配置/message和完整原依赖集合并重新鉴权，不自动换一组来源或复制新的答案状态机

### Requirement: One original reply
应用 SHALL 仅调用可信core reply_for_task保存答案，传入context记录的全部输入依赖；原消息唯一reply、双方读取和内容撤回一致性由core拥有。

#### Scenario: Reply acknowledgement lost
- **WHEN** 原回复已提交但响应丢失并重启
- **THEN** 同task同回复恢复原结果，不新增消息、task、allocation或反向sender执行；异内容不能覆盖原回复

#### Scenario: Membership and source authority change
- **WHEN** 来源可见性或任一成员权限在模型执行后变化
- **THEN** 提交与读取重新按现有core机制检查；隐藏派生答案不删除原历史，也不声称已读内容可被追回

### Requirement: Retained team-value continuation
P7后续交付 SHALL 包含少数相关记录的主动关联及来源对实际研究决策/动作的可追踪影响；本QA切片不得被当作整个团队价值验收完成。

#### Scenario: Relevant and irrelevant research events
- **WHEN** 后续关联单元处理有关/无关/过时/无权记录与重复事件
- **THEN** 仅按明确相关规则及当前权限选择有界接收者，保留来源与采用/拒绝理由和实际action；无全员广播、无覆盖他人、无消息数替代价值判据


#### Scenario: Lost question acknowledgement followed by configuration replacement
- **WHEN** sender的原问题回执丢失，recipient已更换QA配置，sender以同requestId和正文重试
- **THEN** 先读取原request并核对历史endpoint归属，返回原message/task/allocation，零新派发；换assistant或改正文明确冲突，非not-found错误不被吞掉

#### Scenario: Configuration transaction fails
- **WHEN** 新scope/endpoint创建或旧endpoint停用后配置事务失败
- **THEN** scope、endpoint启用状态、配置revision与current指针整体回滚，不留下有效孤立资源或部分配置

#### Scenario: Original sender recovery after recipient disablement
- **WHEN** 接收者禁用后，仍有效的sender以相同requestId和正文重读原问题
- **THEN** core验证sender原消息权限后，应用只核对不可变历史endpoint归属并返回原回执，不要求recipient启用、不新派发；runtime配置读取仍拒绝禁用owner
