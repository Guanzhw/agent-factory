# Design

## Context

动机见 proposal。已读固定候选的 `session_tools`、`session_setup`、`sessions`、`conversations`、`assistant_messages`、`assistant_events` 与 `application_runtime`：

| 已有 | 真实边界 |
| --- | --- |
| `ResearchSessionTools._function` / `_execution` | 可验证原 task/run 与 owner；`RunContext.session_id` 实际是 taskId，不能当研究 sessionId |
| `ResearchConversations` | 关联原问题、原请求、原会话并采用；当前由人工发起，没有自主继续意图 |
| `AssistantMessages.reply_for_task` | 持久化原回复并核权，尚不发私人回复通知 |
| `AssistantEvents` / delivery lifespan | 同一持久事件表、受控批处理、退出及重试；当前 contentId/订阅 endpoint 逻辑只能处理内容事件 |
| `before_model` / 上下文保护区 | 处理纠正、摘要与来源守卫；没有异步回复采用 |
| `ResearchSessionSetup.prepare` | 生成固定 applicationRef/tools fingerprint，旧会话不能通过新注册热扩权 |

## Goals / Non-Goals

**Goals:** 一对个人助手的一次自主询问→B 既有 QA→A 活跃安全点或安全终态后的有界继续。先完成该纵向链，再扩到完整回归。

**Non-Goals:** 不替换 Agno，不新建队列、消息总线、框架或跨租户 Team；不让 A 直接改 B 配置/资料，不增加自动训练、主机权限或费用计量承诺。新能力初期只用于新配置会话；旧会话保持人工协作。

## Decisions

### 1. 工具用原运行身份，不引入第二套授权

增加研究应用自己的助手目录/提问工具，仍经现有 Function、AdapterRegistration、tool effect 与工具次数控制。输入只有助手 ID 和问题文本；可信 guard 从原 task/run 找到持久研究 turn/session，由 runId+tool callId 派生稳定 requestId。复用前片原子 reservation，原问题记录同时保存发起 turn/原工具 effect 和一次继续意图；不能用模型给出的 owner、allocation 或 sessionId。

查询目录只返回当前成员可见、已开放的助手信息。发问 prompt 说明只发送必要文本；工具不隐式拼接私有历史或读取凭据。这不等同证明模型永不在自行生成的文本中泄露敏感语义，真实模型案例需核对实际发出内容。

### 2. 在既有事件生命周期中增加一个私人回复类型

沿 `AssistantEvents.events` 的 JSON body 增加显式的私人回复 discriminator，正文只保存 messageId 与经应用核验的原发起 taskId，不伪造 contentId 或 endpoint。仍由已有 `deliver_batch` / lifespan 处理、限量、退出与重试；普通内容事件及 deliveries 保持原路径，无第二个 worker 或 delivery 表。

Research QA 记录回复时，在已有 metadata transaction 中一并生成唯一回复事件。应用从原问题关联核实 A 原发起 task 与自主意图；core 复核消息与 task 的 owner，并沿既有 `ApplicationRuntimeRegistry` 的原任务 owner 调用一个窄私人回复 hook。core 不查询 Research 表或导入其模块。旧人工问答没有自主意图，因此不自动生成唤醒授权；重复 reply 复用同事件。

私人事件不走内容事件的订阅 endpoint/预算分配，也不借用 content publication 权限。event owner/读取投影须保持私人收件者边界；记录与通知不能把正文暴露在全员内容列表。暂时缺少原 app handler 时保持待核对，不能错误置为已采用。

### 3. 采用与再次执行是两个安全点

持久原问题意图记录 received/pending/consumed 或 stopped/blocked 的实际关联，不复制一套消息执行状态。活跃 turn 在 `before_model` 的短事务内核源、核原操作、核容量并将不可变回复放入保护区；只有实际进入原主请求时才标纳入。摘要前后沿已有守卫重核；工具执行中不修改其原参数或假称即时干预。

原 turn 已安全结束时，投递 hook 以原 messageId 派生唯一 next-turn request，检查 session stopped、maxTurns、模型资源、原任务/effect 和容量。复用原 `_reserve` 的准入主体，但自动路径不得清 stopped；人工新轮和自动轮通过同一 admission→session 锁序竞争。已出现活动轮时把回答留给该轮安全点，不开并行研究。一次意图只允许一个后续轮；继续轮仍有原工具和机器限制，不表示 token/费用计量。

模型调用、队列提交均在事务外，意图消费、原回复绑定和下一轮 reservation 同事务。提交后退出沿原 request/task 核对，不能以 event 重试重复启动 UNKNOWN。单纯页面 GET 不执行；重启后的自动投递只履行原自主发问已经保留的继续意图。

### 4. 停止、恢复与界面

停止与自动准入使用既有锁序；停止时废止未消费意图，已创建任务按原取消路径处理。迟到回复保留可核权记录，但不得自动清 stop。只有成员以后明确继续，才依既有人工语义开启新轮；不把这个动作固化为每条回复审批。

复用问答卡片和执行事件，显示发起方式、等待对象、回复到达、待纳入/已纳入及具体阻断。新会话创建处简短说明可自主协作及停止边界，不增加新角色或逐项审批表单。采用与回答存在不代表实验验证成功。

## Risks / Trade-offs

- [私有事件不适合现有 content 分支] → 独立方案审查专门核对一个 discriminator 分支与原 owner hook；若必须引入通用路由框架或第二队列，停止该扩展并收窄实现，不假装已有接线。
- [回复/人工继续/停止竞争] → 真实 PostgreSQL 并发与实际进程退出反例，保留原意图/任务，无新增补偿性重发。
- [引用增加容量或后来撤权] → 原保护区与当前来源核验；过大/失权就地受阻，不能缩短原文来强行通过。
- [多次往返耗额度] → 每原问题至多一次后续轮，沿现有 maxTurns、工具次数、B 预算及原消息约束；首次验收只一对助手一次往返，不宣称全局费用上限。

## Migration Plan

PR #153 合入后核其 tree/base。私人事件使用新 body 类型、原问题新增可选自主意图关联；旧记录缺少意图始终维持人工语义。新工具进入新的配置 fingerprint/applicationRef，旧引用不改。回退停止处理新私人事件但保留其原记录，不删数据、不把未确认状态迁成成功；部署仍须独立门槛与用户环境。
