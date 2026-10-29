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

### 2. 同一私人协作事件覆盖发问和返回

沿 `AssistantEvents.events` 的 JSON body 增加显式的私人协作 discriminator，正文只保存 messageId 与经应用核验的原发起 taskId，不伪造 contentId 或 endpoint。工具在原消息/origin/预算/继续意图提交的同一事务中创建唯一事件，不等 B 回复后才建事件。仍由已有 `deliver_batch` / lifespan 处理、限量、退出与重试；普通内容事件及 deliveries 保持原路径，无第二个 worker、scanner 或 delivery 表。

worker 从原消息/任务/回复与应用意图推导阶段：真正无原 task 时沿原预授权 `messages.recover` 准入 B；已有 task 则只读等待原回复，RESERVED/UNKNOWN 不重放。B QA 继续既有 `reply_for_task` 写入，无额外发布或消息回调。回复可用后沿 `ApplicationRuntimeRegistry` 原 A task 的 owner 调用一个窄协作 hook；应用再次核原问题/意图，core 复核消息与 task owner，不查询 Research 表或导入应用。旧人工问答没有自主意图，不生成此事件；不为每条回复建新事件链。

只有实际纳入或明确停止/永久受阻才完成事件。A 活跃但尚无安全点时保持 pending 并更新已有 attempted_at，公平轮转；如果 A 随后结束且没有下一次模型调用，仍由同事件观察终态并按一次意图继续，不能提前 scanned 后丢失唤醒。

私人事件不走内容事件的订阅 endpoint/预算分配，也不借用 content publication 权限。event owner/读取投影须保持私人收件者边界；记录与通知不能把正文暴露在全员内容列表。暂时缺少原 app handler 时保持待核对，不能错误置为已采用。

private 分支必须在内容路径读取 candidates/contentId 前判别，所有 listing/detail 均按类型及原 owner 投影。现有停止栅栏只在 content delivery_id 的准入接线中生效；本片须把可信原 private event 的停止检查带到 B 新任务及 A 自动轮的真正 reservation 事务边界，重核同一个 `admission_stopping`，不能只检查 batch 顶部。退出胜出时不新建任务、事件保留 pending；已有任务仍可只读核对。该引用只能由可信 worker/原意图派生，不接收客户端 event 或 owner 参数。

工具 effect 结果未知时只允许原 request/owner/助手/正文完全匹配的持久消息证明“问题已保存”，据此核对原工具回执；这不能把 B 的任务 UNKNOWN 标成成功，也不重发问题。原消息不存在或读取出错则保留 unknown，不能绕过通用 mutating effect 守卫或以 404 当首次执行许可。原消息已保存但 recover 前退出的窗口，由上述同事务事件负责接续 B，不依赖模型重调工具或人工代替自主路径。

原 A 的原生队列重试可能在原消息已提交后留下 `RESEARCH_EFFECT_UNCONFIRMED` 或 `RESEARCH_RESTART_REQUIRES_RECONCILIATION`。应用先沿既有严格 native binding 证明原 A ticket/run 已真实结束，逐项证明其非空 effects 全部是本 turn 的原提问：owner/session/turn/task/run/call、canonical 参数、原 endpoint/正文与持久消息一致，且每项都有精确的 DONE“问题已保存”回执，才可核对上述两种阻断。Research 的 blockReason 本身也被视为 custody，不能要求被它阻挡的 metadata terminal 先成立；短事务内仅暂除该应用阻断后重核全部其余 custody/effects，有其他持有则原样恢复。无其他持有才提交解除阻断，随后必须等待既有 observer 正常结算原 task/turn 终态，后续 event 才可通过 `_safe` 新建轮次；解除阻断这一步不启动新轮。不手写旧 task/run 的 status/result/terminal，不派发旧 A/B，也不解除其他阻断。任一文件/命令 effect（即使 DONE）、缺失或不匹配回执均保持阻断；随后仍由原事件核停止、权限、轮数和容量，最多建立一次新轮。这是 Research 对已保存问题的窄核对，不推广为通用 UNKNOWN 自动恢复。

### 3. 采用与再次执行是两个安全点

持久原问题意图记录 received/pending/consumed 或 stopped/blocked 的实际关联，不复制一套消息执行状态。活跃 turn 在 `before_model` 的短事务内核源、核原操作、核容量并将不可变回复放入保护区；只有实际进入原主请求时才标纳入。摘要前后沿已有守卫重核；工具执行中不修改其原参数或假称即时干预。

采用集合保留旧 `body.assistantReply` 的人工单值读取，并增加有限的自动回复集合，按 questionId 去重、原问题创建顺序稳定排序。保护区、容量、摘要及撤权守卫检查全部元素，不覆盖旧单值；人工已采用同一问题时标原意图已消费，不再为它另开轮。一次安全点或自动新轮 reservation 批纳入届时可用的集合，不按每条回复强制各建一轮；后到回复沿同事件的 active/idle 规则处理。有限性来自现有工具/轮数与真实上下文容量，不添加第二种摘要或无限附件。

原 turn 已安全结束时，投递 hook 以原 messageId 派生唯一 next-turn request，检查 session stopped、maxTurns、模型资源、原任务/effect 和容量。复用原 `_reserve` 的准入主体，但自动路径不得清 stopped；人工新轮和自动轮通过同一 admission→session 锁序竞争。已出现活动轮时把回答留给该轮安全点，不开并行研究。一次意图只允许一个后续轮；继续轮仍有原工具和机器限制，不表示 token/费用计量。

模型调用、队列提交均在事务外，意图消费、原回复绑定和下一轮 reservation 同事务。提交后退出沿原 request/task 核对，不能以 event 重试重复启动 UNKNOWN。单纯页面 GET 不执行；重启后的自动投递只履行原自主发问已经保留的继续意图。

### 4. 停止、恢复与界面

停止与自动准入使用既有锁序；停止时废止未消费意图，已创建任务按原取消路径处理。迟到回复保留可核权记录，但不得自动清 stop。只有成员以后明确继续，才依既有人工语义开启新轮；不把这个动作固化为每条回复审批。

任务失败清理与成员停止会话必须区分。沿既有 `ApplicationRuntimeRegistry.mark_cancel` 传递可信调用原因，不从展示事件列表推测最后一次原因。生命周期观察者只在首次设置原 task 的取消标记时调用应用 hook，保留首次原因；先取得既有 admission 锁再改任务行，与会话写锁序一致。明确取消的 `Store.request_cancel` 每次都调用 hook，即使标记已存在；`cancel_subtree` 复用这个明确取消入口，协议拒绝始终走明确取消；首次撤权清理会停止。已有取消标记后的撤权仍由原执行和后续准入的当前授权守卫阻止使用，不以重复应用 hook 通知为保证。

Research 仅在 `native-failure` 且原 task 有两种已列明的重启/效果核对 guard 证据、没有 protected failure/已有停止、非空全部 effects 精确对应已保存原提问时，可以保留未消费意图。保留意图不是准入；UNKNOWN 回执仍须按原消息核对，所有 DONE/终态/其他 custody 条件满足后才按上节继续。其他失败、混合效果、缺失证据及明确取消均停止，不清任何已存 stop。迟到的旧 task 清理不得影响后来已明确开始的新轮。

A 在发问事务提交前停止，不能再提交新问题；消息已经提交给 B 后，该原问题属于 B 已配置的接收授权，A 停止不撤销它。即使 B 尚未建立 task，worker 仍可按原消息及 B 当前有效预算补齐 B 原任务；A 的回复采用和自动继续则保持停止。B 始终可按自己的原任务权限停止，不能借“恢复 B”自动启动 A。

复用问答卡片和执行事件，显示发起方式、等待对象、回复到达、待纳入/已纳入及具体阻断。新会话创建处简短说明可自主协作及停止边界，不增加新角色或逐项审批表单。采用与回答存在不代表实验验证成功。

## Risks / Trade-offs

- [私有事件不适合现有 content 分支] → 独立方案审查专门核对一个 discriminator 分支与原 owner hook；若必须引入通用路由框架或第二队列，停止该扩展并收窄实现，不假装已有接线。
- [回复/人工继续/停止竞争] → 真实 PostgreSQL 并发与实际进程退出反例，保留原意图/任务，无新增补偿性重发。
- [引用增加容量或后来撤权] → 原保护区与当前来源核验；过大/失权就地受阻，不能缩短原文来强行通过。
- [既有 QA 回复尾窗] → 实际退出已证实：回复保存后、原生 job 尚未终态时，同一 B run 的重试可再次调用只读模型；原回复不可覆盖。该路径在本片之前已存在，原消息/任务去重不等于模型请求恰好一次。QA 实现源码参与旧 pin，不能直接修改后声称旧任务兼容；单列后续兼容方案，当前不宣称此尾窗已修复。
- [多次往返耗额度] → 每原问题至多一次后续轮，沿现有 maxTurns、工具次数、B 预算及原消息约束；首次验收只一对助手一次往返，不宣称全局费用上限。

## Migration Plan

PR #153 合入后核其 tree/base。私人事件使用新 body 类型、原问题新增可选自主意图关联；旧记录缺少意图始终维持人工语义。新工具进入新的配置 fingerprint/applicationRef，旧引用不改。回退停止处理新私人事件但保留其原记录，不删数据、不把未确认状态迁成成功；部署仍须独立门槛与用户环境。
