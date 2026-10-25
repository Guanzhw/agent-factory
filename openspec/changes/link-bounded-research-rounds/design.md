# Design

## Context

基线 48e642f 合入 #99 7d0701f，使用显式 ResearchServices；原规划来自 d8f089f。动机见 proposal.md。

实际源码边界：
- `autoresearch.py: AutoResearchService.start/tool` 保留原请求、一次派发意图和 research_decision，但 continue 不创建 successor；start 当前重新计算 deadline。
- `autoresearch_children.py: _parent/experiment/_verified_result` 要求 maxExperiments==1，三阶段受管子任务有各自真实身份。该测试 fixture 的评价是 val_bpb=4.0，不能用来证明 ORX toy 的 MSE 或基线晋升。
- `usage_ledger.py: _scope_accounts/begin_attempt/finish_attempt` 持久化 task/ancestor/user 账户，attempt 保存 accountIds，UNKNOWN 保留 hold，同一证据重复结算不重复释放；不同 round root 不共享账户。
- `delegation.py: consume_tool_budget/create` 维持原 root 的 call ID 去重与 child/depth 上限。增加 activity 父任务会挤占这些限制，不采用。
- `billing_mode.py: ledger_for_plan` 对 BYOK 返回 None；默认不启用平台费用管理。不存在默认硬 token/money 计量。
- `lifecycle_observer.py: tick` 排除全部终止的 root，后继恢复不能只依赖 observe_waits 或历史 GET。

## Goals / Non-Goals

**Goals:** 两个独立 native round roots，持久全轮预留，实际基线文件承接，原身份恢复，无 GET 副作用；科研应用 owns 活动策略，核心只 owns 通用额度和 native 执行。

**Non-Goals:** 远程轮次、并行搜索、任意源码候选、通用科研优化算法、训练 checkpoint 验收、真实外部模型兼容和新增执行队列。不修改旧 toy 摘要、不抬 generic child cap、不把 UNKNOWN 当零消耗。

## Decisions

### 1. 首 preset：版本化本地 ORX toy 两轮

选择 `local-orx-toy-iterations-v1` 新 preset/recipe 身份，复用现有真实本地 ORX CLI、task-owned store、guardian 与 artifact custody。证据来自 `orx_toy/evaluator.py`：metric 是 mean_squared_error，improvement=baseline-candidate；`baseline.py` 为常数 1，`candidate.py` 为 2*x+1。首轮原数据 MSE 从 16 到 0。沿用 `comparison_fixture.py` 的 minimize/minimumImprovement=0 和 `comparison_contract.compare_observations` 的严格 delta>threshold：改善晋升，平局不晋升并停止；回退或评价失败也停止。

第二轮 baseline 必须实际使用第一轮 candidate 原始字节，candidate/dataset/evaluator 仍固定，得到 0→0，停止原因 tie。不只把界面 baseline ID 改名。评价输出 status 必须 done，metric/value 必须有限、来源 task/owner/原 process receipt 必须一致，文件摘要须匹配原 recipe；stdout 的描述不能代替 result artifact。

`TaskLocalORXProvider.create_experiment_adapter` 当前没有 baseline_source 参数；`TaskLocalORXAdapter.ensure_experiment/_validate_owned_source` 固定复制和校验 TOY_FILES。需要新增独立 recipe/provider revision 的受信任 baseline-source 输入并校验新 manifest；旧 TOY_FILES 和旧行为不变。新输入只能从已授权本活动前轮 candidate artifact 解析，无路径/任意源码覆盖。root 审查最小复用 seam，不能复制完整 process/cleanup 实现。

baseline pin 最少含 owner、来源 round/task、candidate/source artifact ID 与内容 SHA、candidate 文件 SHA、dataset/evaluator SHA、evaluation artifact ID/SHA、原执行回执身份。首轮引用已审查 seed，后续引用活动晋升记录。toy 无训练 checkpoint，API 显式标识 sourceArtifact；科学三阶段 checkpoint 路径继续独立回归，不声称已接入迭代。

### 2. 应用表和原请求状态机

新增 activity 保存不可变 goal/preset revision、资源/模型/应用 pins、policy、总 cap、absoluteDeadline、current baseline、cancel marker；round 保存 ordinal、previousRound、baseline pin、request ID、plan/task/run、allocation ID、dispatchAttempted、评价/结算摘要。唯一约束 `(owner, requestId)`、`(activityId, ordinal)`、previousRound 的唯一 successor。每轮仍是独立 root。

在共享 Store.transaction 中先提交唯一 successor intent 与完整 round allocation；缺钱/工具/轮次/时间则整个事务失败。准备 plan/task 时绑定该 allocation，冻结 plan hash；未绑定／绑定冲突不能 dispatch。派发前单调设置 dispatchAttempted，之后使用 NativeBridge.submit → Store.accept，异常标记原 admission unknown。故障恢复只查询原请求、原 task/native admission，未知不能换 request 或重派。

API 建议（受信任内部入口，具体 public schema 由 root owns）：
- `ResearchIterations.start(owner, preset_id, goal, request_id, limits)` 创建活动和首轮意图。
- `advance(owner, activity_id, previous_round_id, decision_ref, request_id)` 只接受原独立评价及 continue 意图，原事务中完成晋升和下一轮预留；并发调用返回同一 successor。
- `reconcile(activity_id)` 处理已持久意图／停止事实，不从 GET 调用；`cancel(owner, activity_id, request_id)` 先提交取消 marker，再取消唯一 active round 原树。
- `inspect(owner, activity_id)` 纯读谱系和预算，不触发 dispatch、晋升或结算。

现 `AutoResearchService.start` 可提取受信任 reserve/bind/dispatch seam，并允许继承绝对 deadline；单轮 public 默认不变。toy 使用其现有 native application/tool 路径，不强行调用要求训练 checkpoint 的 scientific child API。新活动扫描器通过 ResearchServices 显式装配和关闭，仅有界扫描 pending 活动、调用原 native API；不拥有第二套任务执行队列。

### 3. 全轮 allocation，避免活动双 hold

活动账户 `available = total - settled - held`。在 successor intent 事务内预留全轮 cap，固定 allocation ID；轮内 task/user 和 round allocation 账户继续约束每次实际调用。活动父账户不再加入每个 provider attempt 的 accountIds，避免全轮 hold 与单次 hold 重复计费。user 账户仍仅记实际 attempt，不因活动预留重复 hold。

核心最小接口建议放 `usage_scopes.py` 并由 UsageLedger 集成：
- `create_scope(owner, scope_id, immutable_limits, commitment_sha)` 幂等创建原总承诺。
- `allocate_round(conn, owner, scope_id, allocation_id, immutable_intent, caps)` 在 caller 事务与 ledger 锁下预留；无网络/provider 调用。
- `bind_root(conn, allocation_id, task_id, plan_sha)` 一次绑定；begin_attempt 通过原 task/ancestry 查持久绑定，并给轮内 allocation 账户记 hold。
- `settle_round(owner, allocation_id, evidence)` 从原持久账本与原停止证据构造结算，不接受客户端自报用量。重复相同结算幂等，累计不能下降，closed 不能 reopen。

复用 `_hold/_account` 和 finish_attempt 的不重复释放规则；不把 local allocation 写成 remote grant，不改变远程 proof/statement 身份。新 scope/binding 表只存通用 owner/task/commitment 身份，core 不导入 ResearchServices。锁顺序固定为 ledger 短事务锁，再 activity/round 行锁；其他路径禁止反向持锁调用，native/API 调用全在提交后。

释放剩余额度必须同时满足：原 root/子树已停止、原效果已结束、无 RESERVED/UNKNOWN model attempt、无未决 admission。已结算的实际用量即使取消/撤权仍计入；耗用超预留也按真实证据记账并停止后继，不能截断为 cap。失败但已知未派发可以凭原正向证据退还额度，不能仅凭异常退款。停止证明和费用证明是两种不同证据，不能互代。

### 4. 各维度的真实边界

轮次 cap 硬限制本活动唯一意图数；toolCalls 预留本轮 root 上限，按 af_delegation_tool_calls 的原 task/call ID 计数收尾；重复 effect/receipt 不再次消费。绝对 deadline 不随新轮重置，每轮启动前必须有足够已声明 wall bound，并在执行入口检查活动取消/截止状态。每轮资源、outputBytes、maxChildren/maxDepth 仍受原计划约束；不把每产物上限说成跨轮存储总量。

首 toy zeroModelCalls 是实际受控证据，不能推广成 BYOK 的零 token/money。账本启用时验证全轮 token/money allocation 与实际累计；BYOK 无计量时 API 显示 unavailable/unknown，不接受声称可硬执行的 token/money cap，只保留 round/tool/deadline 硬限制。无需为启用迭代而打开付费模型。

## Risks / Trade-offs

- 原 toy 固定文件与动态 baseline 冲突 → 新 immutable recipe revision，旧 hash tests 不动；实际 artifact bytes 验证第二轮。
- intent 与 allocation 分步提交留下 free successor → 同事务预留，绑定后才能执行；三个 crash cut 验收。
- 全轮 hold 加每 attempt 再向 activity hold → 分离活动预留与轮内账户，只在 settlement 向活动累计。
- task terminal 被误当 usage settled → 明确同时检查停止和原用量；UNKNOWN 故意阻塞后继。
- 终态 root 不再被 observer 扫描 → 应用 pending-intent 扫描由 #99 graph 生命周期管理，先停准入再 #98 收尾。
- 模型输出 continue 绕过剩余额度 → continue 是意图，不是授权；每次核对原活动 pins、当前成员/资源权限和原额度。

## Migration Plan

新增表与显式 preset opt-in，历史单轮不补造 activity，不改原 plan/hash。先实现不可执行的持久意图/额度契约，再接本地 recipe 和 native start/recovery，最后 UI。回退停新活动准入，保留原活动观察和取消服务至收尾。当前只有规划，无两轮、PG、浏览器或外部服务通过证据。
