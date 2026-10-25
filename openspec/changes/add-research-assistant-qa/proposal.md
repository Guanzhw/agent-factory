# Proposal

## Why

当前项目的内部round endpoint不是成员的长期研究助手，原私有消息也没有应用层经验问答消费者。需要一个稳定的成员研究身份和只访问双方可读团队研究记录的受预算QA路径；不能以另建个人记忆、回答ACL或反向消息执行来填补这些缺口。

## What Changes

- 每个成员一个持久researchAssistantId，当前QA配置与内部endpoint可更换，身份不等于常驻进程。项目新增同名关系字段，旧assistantId仍指历史core endpoint。
- 可选应用装配固定tool-free QA Workflow及无外部副作用的本地EnvironmentLimits声明；复用现有setup明确保存/发布与个人模型连接，不借研究compute环境、不默认选模型或授无限额度。
- QA从原message/task身份读取问句，输入仅双方当前可读team研究记录的有限交集；答案沿独立core原消息reply端口保存/读取，撤回隐藏派生正文，无反向send或应用答案表。
- 明确最小HTTP：个人助手创建/读取、显式配置、有限团队助手目录、按稳定助手发起私问；后续主动关联及source→decision→action任务仍保留，分步验证不删完整旅程。

## Capabilities

### New Capabilities

- `research-assistant-qa`: 稳定成员研究助手、受限私问和明确出处的经验回答。

### Modified Capabilities

无既有归档能力替换；与活跃restore-team-research-application的P7协同，不重定义core消息权限。

## Impact

预计仅applications/research身份/QA/setup/public、非破坏项目列迁移及对应测试；deployment负责显式注册，core无研究import。依赖已集成消息预算/message_for_task与待独立review的core reply_for_task，不实现新的通用消息服务。视觉设计确认已解除，本轮可提供真实接口给已确认UI接线，但本提交只含spec。真实C02/C03及D类参数尚未冻结，仍BLOCKED；无付费模型/GPU调用或生产共享动作。
