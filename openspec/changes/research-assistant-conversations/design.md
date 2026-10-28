# Design

## Context

动机见 proposal。暂基线 `9566a94f5df36e2f2dae2e724b82ddb5f4aef3e5` 的实际接线：

| 已有实现 | 本片复用边界 |
| --- | --- |
| `AssistantMessages._reserve/send/recover/request/read` | 消息、原 requestId、原 endpoint/预算绑定；只有新 task reservation 才提交原生运行。普通重复发送只读。 |
| `ResearchAssistants.question` | 同 requestId 查历史配置并核对文本/助手；配置变更不把旧问题重定向到新 endpoint。 |
| `ResearchQA` 与 `reply_for_task` | B 的预授权 QA 任务、双方可读来源、绑定原任务的回复；不等同完整研究或代码执行。 |
| `ResearchSessions` 与上下文整理 | A 自己的任务、显式下一轮、来源守卫和容量限制；目前无问题/回复关联。 |
| `AssistantQuestions.tsx` | 已有目录、提问、原问题/来源查看；缺原会话归属、接收列表和主动恢复。 |

`Store.transaction` 与 `GovernedStorage` 已能借用同一 metadata connection。这里是一个进程内的 PostgreSQL 元数据事务，不是跨服务分布式事务。执行调用必须在提交以后。

## Goals / Non-Goals

**Goals:** 整体在获准范围内自主异步协作。首片先完成一次人工 UI 提问从 A 原会话出发，B 既有 QA 回答，A 回原处查看并选择采用；每个中断窗口都可找到原消息并保留原任务身份。紧接续片接 Agent 主动发起和返回证据自动采用，首片的人工操作不是全局审批门禁。

**Non-Goals:** 首片未覆盖工具发起与自动返回采用，其接线见后续阶段；不新增队列、第二消息总线、常驻收件代理、Team 或角色系统。B 配置 QA 是其已有执行授权，不让 A 临时代替 B 配模型/预算或取消 B 的任务。

## Decisions

### 1. 原 requestId 关联，在已有事务中原子提交

新增 Research 专用关联表，以 `(owner_id, request_id)` 唯一标识，保存 `session_id`、稳定 `assistant_id`、绑定三者及确认文本的 fingerprint、时间。消息内容、消息 ID、任务状态和预算仍以现有 message command/receipt 为准，不复制一套状态。

会话提问的同步准备路径先核验 owner 的会话及原绑定，复用助手问题的历史/当前配置解析，再调用现有消息 reservation，最后写关联；都借用同一个 `Store.transaction`。仅暴露现有 `_reserve` 为可信进程内的窄 `reserve` 接口，不增加 callback、消息总线或可由客户端指定的 allocation。统一更新实际调用者。保持既有预算锁→消息锁顺序，关联写入不获取会话全局写锁，不修改 session JSON。

关联缺失而原 requestId 已被独立问答使用时拒绝，不把旧问题静默绑定到新会话。并发同请求须核对完整 fingerprint；任一绑定/写入失败回滚消息、预算及关联。原子提交意味着不会出现已发送但原会话找不到的孤儿。

备选“先关联、另一次提交消息”虽然无需暴露 reservation，却新增了只有意图、没有消息的恢复状态；本片不选。使用原 requestId 而不是先要求 messageId，避免为获取 ID 提前发送。

### 2. fresh 初次发送与接收者主动恢复分开

首片人工路径中，事务提交后仅本次 fresh reservation 沿现有 `recover(recipient, messageId)` 启动原预授权任务；这与现有 `send` 的首次执行授权相同。重复 A 请求、列表、刷新、详情均只读。提交后、调用前退出时，消息在双方入口可见；B 可点击“接续原问题”重入。后续获准自动投递接续须沿现有可信 delivery 身份，不能把这个人工入口解释为每条消息的永久审批要求。

接续仍核验原 sender、recipient、endpoint、allocation 和原请求 fingerprint。已有 task（包括 reserved/unknown/accepted 且 runId 缺失）只核对原请求；不发第二次执行、不换 endpoint、不另分配预算。新任务准入由原 reservation 的 fresh gate 决定，不能把某次 404 或读取失败当作执行许可。真正数据库错误传播。B 的旧 endpoint 被停用时无任务的旧消息拒绝启动；已有任务照原身份查看。

### 3. 最小接口与数据范围

| 层 | 新增或窄修改 |
| --- | --- |
| Core | 暴露现有消息 reservation；增加 owner/recipient 范围内的有界消息列表。保留 send、recover、read、reply 与预算契约，不新增 dispatcher。 |
| Research 服务 | 一个会话问题协调模块负责上述关联事务；复用助手的目标/历史绑定解析，避免另一套权限策略。接收列表仅展示属于 B 的 Research QA 原消息。 |
| Research HTTP | `POST/GET /research/sessions/{id}/questions`（POST：requestId、assistantId、text；GET：游标分页，可按 requestId 精确核对丢 ACK）；`GET /research/assistant-inbox`；`POST /research/assistant-questions/{id}/recover`。已有原问题详情和来源接口继续使用。 |
| 下一轮请求 | 人工路径增加可选 `assistantQuestionId`，值就是原 messageId；每 message 已有至多一条不可变回复，不造 reply 实体。一轮最多选择一条，未回复或非 available 时拒绝。原请求 fingerprint 纳入原消息 ID 及不可变回复/来源绑定；重复同请求只读原轮。 |

上述路径均在现有 `/api/factory` 下。恢复接口由登录 B 调用，只接受消息 ID，无 endpoint、owner、allocation、delivery 或任务替换参数；限定既有 Research QA 原消息。A 的私有 origin association 不返回给 B，B 只看到 A 确认的问题文本及原消息已有身份信息。

### 4. 人工路径选择采用；两条路径共用来源与授权边界

首片人工路径中，A 在回复卡片选择“用于下一轮”，提交自己的下一轮指令。服务核验原消息属于该会话/A、回复可读、双方有效成员及全部来源当前可读，再把不可变回复快照与 message/endpoint/task/source 标识绑定到新轮；作为引用证据，不作为用户指令或任务成功证明。此 UI 路径未选择、仅打开或收到回复不运行模型；后续自主路径在原授权内自动关联/采用，无需为每条回复再加确认。

沿已有会话投影/来源守卫接入选中回复：原问题与回复文本、来源/原任务身份留在保护区，不能用摘要替代。以后每次主请求/辅助摘要前重新核验这些已采用消息及来源；摘要返回后再次核验，撤回后不得把迟到结果送入主请求。保留现有 12k 投影、3k 摘要预留、48k 摘要输入限制；采用造成超限时在准入处明确拒绝，不截原文、不忽略该回复、不创建执行。

撤权也作用于 A 会话详情/卡片内已采用的引用副本：隐藏该副本正文/来源，保留原 question ID 与可见状态；旧摘要、已保存请求不得绕过守卫再次发给模型。这不是删除所有旧任务历史或清空数据库。

### 5. 三处小界面复用现有组件

原研究会话增加“向同事助手提问”及有界已发列表，保留未发送草稿并明确只发送当前文本；关闭/返回仍回原会话。助手页提供“收到的问题”，B 打开原问题后可在服务允许时主动接续或进入自己的原任务。原问题/回复卡片显示独立的送达/任务状态、回答与来源、采用动作；没有证据时说明不足，不伪造引用。

B 尚未配置或预算耗尽时，A 保留草稿并看到具体原因；B 自己的入口指向既有配置页，不让 A 代配，也不把消息持久化当作已获执行授权。

A 只能停止自己的研究任务。B 停止仍走原任务控制；A 的问题卡片不提供越权停止。回复存在不代表任务已完成。B 浏览器离线时已接受的任务由既有原生 runtime 执行，无新增轮询执行器。桌面手机均验证用途、下一步、结果和返回上下文，而不是仅统一 CSS。

### 6. 紧接自主路径：复用边界及待接线项

自主协作是下一小片的交付目标，不是永久非目标，也不是本片已经实现的能力。现有 `AdapterRegistration`/原生 registry 可接研究问答工具；`AssistantMessages` 复用消息、原请求、预算和私有回复；`AssistantEvents`/`assistant_delivery_lifespan` 已有内容事件订阅、持久 delivery、deadline/传播上限和受控投递。现有事件是内容通知，不能假称已能自动路由私人回复，也不能为了适配它而发布私密问题。

下一片须定义最小工具 owner/run/原操作绑定、原会话关联，以及私有回复到既有事件/delivery 的必要窄接线；沿现有预算、取消与原请求恢复，不创建第二总线或泛型代理循环。Agent 在既定研究目标、共享范围和预算内选择接收者及必要文本，返回证据自动关联并在合法安全点采用；必要的新模型执行必须仍走既有原生准入。停止后可记录迟到回复，但不擅自唤醒已停止任务；已有 UNKNOWN 操作绝不重放。超权限或修改他人资源拒绝，私有会话/凭据不因协作自动共享。

共用 reservation/receipt/authority 校验真实 owner、原 run/request、共享权限和预算，不新增或依赖“人工已批准”标志。续片工具从可信 RunContext 派生发送者、会话绑定与幂等 ID；不能接受客户端提供 owner/allocation/run 来模拟自主授权。

续片验收：无需逐条确认的一次自主问答；B 离线后完成及 A 原会话自动关联/采用；重复/乱序通知只采用一次；重启不重发未知任务；预算耗尽/停止/撤权时无新执行或越权内容；两用户证据隔离。准确的私有回复通知接线和安全点由续片 spec 独审后实现，本片不虚构该能力。

## Risks / Trade-offs

- [提交到启动之间仍可能退出] → 首片人工路径保留持久关联并由 B 主动接续；续片可信自动投递仍守原绑定与 UNKNOWN 不重放，不把重复 UI 请求当执行许可。
- [撤回来源或成员权限使历史证据不可用] → 原记录留存，展示不可用并阻止带该证据的新模型准入；不缓存旧授权、不自动换来源。
- [旧配置已停用] → 原问题不迁到新配置；B 可查看旧状态，用户另发新问题才使用新配置。
- [选中回复消耗保护区] → 复用真实投影容量检查，超限明确拒绝；本片不增加另一种压缩或无限附件机制。
- [锁顺序及已有 requestId 冲突] → 真实 PostgreSQL 并发/回滚反例检验；不以 SQLite 或仅 UI 测试替代。

## Migration Plan

实施前以先片最终 main 核验差异。只加关联表、可选请求字段及入口；旧消息/任务/独立问答继续可查，不回填私有会话归属、不改 Agno 3.1.0 或已有任务执行语义。部署回退可回退入口/代码但保留新增表和原记录；不清理数据。全站 UX、硬件容量和用户环境部署另列后续阶段。
