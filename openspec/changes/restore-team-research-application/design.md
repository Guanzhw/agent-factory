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

### 4. 目标修订与停止

用户提交目标修改附当前版本；冲突返回当前版本，不最后写入覆盖。修改先形成新约定与影响说明，明确后生效。默认允许已在途的不冲突操作按旧目标完结并标为旧版证据；与新目标冲突的操作请求原身份取消，正向停止证明到达前不启动冲突后继。目标修订不重置scope消费；需要增加预算是另一次明确资源约定，不隐式扩容。整体停止仅阻止新尝试；UNKNOWN和子任务清理继续显示待核对，不要求伪造清理完成才能保存研究结束理由。

### 5. 自动记录与限定共享

实验开始事务保存领域记录并产生通用事件；运行完成后从core原输出追加记录修订。记录包含作者、项目/goal版本、实验条件、运行/产物引用、观察事实与agent解释；不把LLM自评当验证。产物字节仍归core，应用只确定哪些条件/证据/结论进入共享视图。科学验证来自预先声明评价标准与实际指标；未知结果不填成零分或失败。

P6需要core限定内容读取契约：当前成员读取已发布的精确artifact引用，不能冒充作者打开全job；撤权和禁用实时生效。应用用core权限判定共享读/作者写，不建立自己的成员目录/ACL。没有此port前只能实现本人记录和纯数据投影，禁止以跨owner store读取替代团队证据API。应用事务和通用outbox原子性由P3确认，不能假定两个service调用天然原子。

### 6. 离线问答与定向关联

使用独立的研究问答native组件与端点，tool集合只有当前授权的记录检索和答复写入，不注册训练、GPU分配或实验提交工具；通过实际guard/dispatch计数证明限制，提示词只是行为说明。该端点使用接收者自己的模型/预算，不接受发送者替换连接或执行模式。引用材料中的指令视作内容，不成为工具权限。

应用选择少数相关端点及来源，通用P3负责事件订阅、投递去重和预算边界；不用全员广播兜底，不建专用mailbox轮询链。关联属于分析作者的新记录，引用原作者版本和条件；不得覆盖原文。以source→decision→action及相关/无关/过时负对照验证价值，不以消息数为收益。通知频率仍可按冻结策略配置，不能虚构已批准的全局偏好。

### 7. 成果与中文UI

最终manifest链接原代码commit、依赖锁、命令、数据位置/hash、非秘密配置、运行证据、指标、负结果和剩余问题；归档核验先于远端清理。生成报告不能代替独立复现。另一成员不看原聊天按包执行，确定性输出精确核对，随机/GPU容差须事前冻结。

主界面为自己的助手与项目概览，详情按目标/实验与运行/证据/协作/成果下钻；复用core登录、导航、资源配置，不另造账户页。支持空状态、直接URL/刷新、退出重登、任务未知与清理提示；无旧研究页面残留。无需为该应用重做全站设计系统。

P4写入在发送前按当前owner及project/new保存原action/body/requestId到本地sessionStorage；408、网络错误及5xx保持未确认，重载后只允许用户显式按原请求重试，不自动提交。成功或首次请求确定拒绝才清除；已不确定原请求的后续401仍保留身份。仅保存本次非凭据输入，不跨owner恢复，不扩成通用执行恢复器。

### 8. P4显式装配入口

Python新增deployment的research组合入口，调用既有ApplicationAssembly安装research.public；默认agent-factory入口不安装应用。发行wheel可包含应用包，但standalone core安装仍不包含它。Web复用Workspace与核心Pages，通过独立research-composition/research-main静态入口注册研究目录卡和project URL；Vite显式research mode选择该入口，默认构建不导入研究应用。架构checker登记research拥有边界与两个显式composition roots，测试发现纳入应用目录；不增加动态插件发现或第二身份系统。

## Risks / Trade-offs

- [P1–P3与限定内容port尚在实施] → 按下表接入门槛推进，依赖未过不写伪实现或临时跨权限通道。
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
| P1端点/P2消息 | add-member-assistant-messaging正在实现 | 端点owner/app pin、固定配置、消息双方读、原request/task关联及重复不dispatch通过 |
| P3事件/自动预算 | 尚未交付 | 同事务outbox、去重、receiver预算/TTL、循环限额及崩溃恢复责任明确，不重派UNKNOWN |
| 限定产物共享 | 现有artifact按task owner读 | 精确内容授权/撤权测试通过；应用不能代理全job读取 |
| 预算与child接入 | core已有LocalBudgetScopes/DelegationService，public context未暴露 | 最小可信composition桥接验证原run/plan绑定、取消与UNKNOWN；不建立通用反射服务层 |

## Open Questions

正式研究任务/模型参数、调用预算、GPU主机及数据、科学容差和代表性容量负载待正式run前冻结；不阻塞上述确定性实现。额外评论/复核/分支、原始数据或私聊共享不在已确认范围内，默认不开放；若以后提出，另更新规范。没有将这些未知项包装为本次已验收能力。
