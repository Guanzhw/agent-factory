# 独立方案审查

**结论：PASS（方案可实施，不代表代码或运行验收通过）。**

- 非作者主审：`context_capabilities`；并行非作者事件/停止边界复核：`compare_review/hook_early_review`。Coordinator 编写四份方案；主审只写本记录，不改产品或其余方案。
- 原产品基线：`2f324a80ea72a78951e6ecb50d1ec0c4887b063e`；初稿：`0c72e65c0bc1d3cc61c515dba337f379940a4e2b`；行为方案审定：`51cc25b26865e2cdf3dcb71820547670446bd19b`。其后 proposal/tasks 的实施顺序修订复核通过，并随 `e24b2000ba9b8a4f91341c0f51c7b0a512006bdb` 记录；末尾 SHA256 是该次复核时的历史快照，后续任务勾选及本次停止语义补充见下文。
- 已读取 AGENTS、ARCHITECTURE、OpenSpec explore 指导与实际源码。通过已有本地 CLI 独立运行 `openspec validate research-autonomous-collaboration --strict`。未安装软件、调用模型、启动服务、运行 PG 或改动 PR #153 工作区。

## 已要求并闭合的修正

| 原反例 / 源码依据 | 审定方案 |
| --- | --- |
| A 问题和 origin 已提交、`messages.recover` 尚未调用即退出；此时 B 没任务也没回复，仅在回复时 emit 会漏掉该问题。`ResearchConversations.question`、`AssistantMessages.recover`；A 原 run 的 `ResearchSessions._model_boundary` 会保守拦截有 effect 的重试，不能靠模型重发。 | 原消息/origin/预算/意图/唯一私人协作 event 同事务提交。同一个已有 worker 沿原消息身份补齐真正缺失的 B task，再等待回复；已有 RESERVED/UNKNOWN 不重放。B `reply_for_task` 保持现有接线，不新增 QA emit。未知工具 effect 仅按精确匹配的已存原消息核对“已保存问题”，不把 B 执行状态升级为成功。 |
| B 回复到达时 A 还活跃，但 A 随后直接结束且没有下一模型安全点。提前把事件 scanned 会丢失继续机会。`AssistantEvents.deliver_batch` 现有扫描/重试机制；`ResearchSessions.before_model` 不保证在最终响应之后再调用。 | 未实际纳入时保持 pending，并更新 attempted_at 公平轮转；同一事件随后观察安全终态并履行一次原意图。缺 handler/暂态失败不是已采用；不引入第二 scanner。 |
| 当前 `turn.body.assistantReply` 是单值；一轮多问或人工引用与自主回复并存会被覆盖。`sessions._replies/_reserve/read`、`session_context.prefix/project`、`ResearchSessions.tsx`。 | 保留旧人工单值，新增有限、有序、按 questionId 去重的自动引用集合；全部元素共同核权、检查容量、进入保护区/摘要出处守卫。安全点或一次新轮批纳入就绪集合；人工已采用不再额外唤醒，不默默丢后到回复。 |
| 私人事件不创建内容 delivery，因而不能自动获得旧 `AssistantEvents.validate_admission` 的 shutdown 检查。该方法只在 `Store.reserve_task` 的 delivery_id 分支调用；仅看 batch 顶部有竞态。 | B 新任务与 A 自动轮的真正 reservation 事务边界重核同一个 admission_stopping。退出胜出时不新建任务，event 继续 pending；已有任务仍可读。新增明确验收场景。 |

## 最小接线成立的边界

- `AssistantEvents.deliver_batch` 当前在内容分支直接索引 `body['candidates']`；新 discriminator 必须在此之前分支。私人事件不进入 `prepare/_current/delivery_for_task` 的 contentId、endpoint、subscription 或 allocation 假设，也不伪造内容 delivery。逐事件异常须保留待核对并推进 attempted_at，不能使整批长期卡住。
- `ApplicationRuntimeRegistry.control(original_A_task, hook_name)` 足以复用原应用 owner 路由，没有必要新增服务容器。它本身不是用户授权：core 先以消息 sender A 核 `store.task(originTaskId, senderId)`，应用再核原会话/turn/工具 intent；不能用 B QA task、模型传入 owner/session 或当前随意 app 选 handler。返回 None 或 owner 不可用不能作为成功 ACK。
- event 私人 owner 是原问题发送者 A；`event()` 只向 owner 返回元数据。采用必须经过 `AssistantMessages.read → _reply_snapshot → _require_reply_sources` 或同等现有完整守卫，重新检查双方成员及全部来源，不能凭 raw reply 存在绕过权限。正文仅为证据，不升级为用户指令。
- 模型、队列提交与可能涉及网络的观察在 metadata 事务外；意图、引用、下一轮 reservation 在既有 admission→session 锁序内协调。自动路径不得复用会清 stopped 的人工 `_reserve` 行为。停过的旧意图不因用户以后人工继续而复活。
- `ResearchSessionSetup.prepare` 把工具注册、指令和 schema 纳入 fingerprint，并持久固定 applicationRef；新增工具可仅用于新配置会话，旧引用继续执行原工具集合，无须热扩权或修改历史任务。
- maxTurns、工具次数、原 B 问答预算和上下文容量分别限制各自行为，不宣称 token/费用总上限。此片保留自主 Agent 发问与自动继续目标，不用逐条人工批准替代它。

## 最小接口与停止边界早审

**ABI 方案 PASS；冻结实现及测试仍待审。** 基于 `e24b2000ba9b8a4f91341c0f51c7b0a512006bdb` 核对 core/Research 两作者约定：

- `emit_collaboration(conn, owner, message_id, origin_task_id)` 同事务存原身份；已有 worker 沿原 B 消息恢复后，通过现有 registry 调用异步 `deliver_collaboration(store, origin_task, event_id, message_id)`。True 仅表示持久已纳入/停止/永久受阻，False/None 保持公平 pending，不提前 ACK。
- 内部 `private_event_id` 沿 ApplicationRuns→FactoryAPI→Store 透传，不增加 HTTP 字段。`Store.reserve_task` 保留既有任务去重返回，在真正新 INSERT 前核事件身份及 shutdown；A 的同步 `validate_collaboration_admission` 再借当前事务按 admission→session 锁序核原 intent、自动 turn、请求/plan 绑定和 stop。观察、B recover、队列提交都在元数据事务外。该改动不需要新 registry、总线或通用路由器。
- 本次准确规格补充仅是 design 第4节新增停止解释，以及 spec 的“停止后迟到”限定为 A 执行并新增“A 停止与 B 尚未准入”。已逐项复核：A 在发问提交前停止不得新发；提交给 B 后，A stop 只撤销 A 的回复采用/继续意图，既有原消息仍可在 B 当前有效授权预算内补齐 B 缺失任务。A 不能取消 B 已有任务；恢复 B 也不能解除 A stop。两作者接口与该语义一致，未扩大权限或引入人工审批。

## 实施门槛与未验证项

### 已保存提问的终态核对补充

**补充方案 PASS，尚非实现验收。** 独立复核 design/spec/tasks 增量，并核实 `ResearchSessions.task_held` → `runtime_custody_held` → `Store._observed_locked`/lifecycle facts 的自环：本应用 block 本身会阻止 metadata terminal，不能把 metadata terminal 当前已成立当作解除它的前提。审定为两阶段：先沿既有严格 native binding 证明原 ticket/run 真实结束，且非空全部 effects 逐项匹配原 owner/session/turn/task/run/call、canonical 参数、消息 endpoint/正文及精确 DONE 保存回执；短事务内仅暂除 `RESEARCH_EFFECT_UNCONFIRMED` 或 `RESEARCH_RESTART_REQUIRES_RECONCILIATION` 后重核全部其他 custody/effects，有其他持有即恢复。无其他持有才提交清本应用阻断，本步不启动新轮；随后由既有 observer 正常结算原 task/turn 终态，后续原 event 经 `_safe`、停止、权限、轮数和容量检查才可建立一次新轮。不得手写旧 status/result/terminal 或派发旧 A/B。任一 DONE 文件/命令 effect、缺证据、原 native 绑定/终态未证实、其他 custody 或其他阻断均不得放行。可复用既有 `inspect_subtree` 的严格绑定观察，不需要新 core 绕过参数。tasks 已要求真实退出正例及混合 DONE 文件 effect 反例；仍待冻结实现后的实际证据。

方案无剩余阻断。Coordinator 先核 PR #153 冻结 head/full 状态；方案独审通过后允许在独立依赖分支实施和测试，不修改前片候选。PR #153 最终合入后再核 main/tree 并整合必要差异；未满足前片及本片发布门槛，不提前发布。此顺序调整不改变行为、权限、验收范围，也不代表本次方案证明了代码可运行。后续须按 tasks 做真实 PG 竞争、至少两个退出窗口、脚本原生链、有限真实 Go 和桌面手机验收；未执行不得标通过。完整实现仍需另一位作者之外 reviewer 审查累计 diff、简洁性及精确 head CI。

## 历史方案审定产物 SHA256（实施顺序复核快照）

- `proposal.md`: `6afc849d48437bacd439853836814e826fed79a02d64ad21b86150fea4f0a47e`
- `design.md`: `6f17c16c3afc88071cb18b545c700925677393425d16353a7e61e6d081df6166`
- `tasks.md`: `6b35742c29f05b6ea5045fe610d9db5b5c7531f88c91f3c3671fc8d5fd0b0e39`
- `specs/research-autonomous-collaboration/spec.md`: `5b9798f90b58a9c6dbd52bbe9e107492aa6e4ec76fab79eacdcc2da13b1cc995`

按上列顺序连接 `path SHA256\n` 得到的 manifest SHA256：`33b05b97ab62a2913e4140fb39bc94a9fac855cdd38db043705ce3836924a793`。
