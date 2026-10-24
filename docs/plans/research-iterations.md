# 实现：可追踪的多轮科研与共享总预算

状态：Draft 实现；本地双轮 ORX/PG/native 与浏览器已验证，完整边界与首轮失败见 verification。原规划基于 PR #95 `246f06541b21915392a77555e24f3f617d34de9f`；当前设计基线 `48e642f` 合入 #99 `7d0701f`，stack 在 #99 上，不依赖 #100 或 #102 实现。
OpenSpec：[link-bounded-research-rounds](../../openspec/changes/link-bounded-research-rounds/proposal.md)，具体接口与边界见 [design](../../openspec/changes/link-bounded-research-rounds/design.md)，所有权与验收见 [tasks](../../openspec/changes/link-bounded-research-rounds/tasks.md)。

## 问题与结果

研究记录 `continue` 后，应能进入保留基线、承接剩余预算的下一轮，而不是只留下建议。现有科学父运行只拥有一次实验；这个归属单位可以保留，由科研应用串联多个轮次。

- `apps/research/agent_factory_research/autoresearch_children.py:66-77`：parent run 为唯一键，并要求 `maxExperiments == 1`；远程 children 也按 parent run 保存实验。
- `apps/research/agent_factory_research/autoresearch.py:348-371,420-456`：要求独立结果后记录决策，但该路径没有创建关联 successor。
- `platform/agent_factory/delegation.py:252-286,310-327` 和 `usage_ledger.py:421-440`：已有预算与原生根/祖先身份相连。创建互不相关的新 root 不能自动共享总预算。

## 实施范围

1. 先选择一个 preset，定义科研活动与轮次的最少持久状态：目标、前后轮身份、已选资源/模型、基线引用，以及现有预算维度下的总承诺和剩余额度。
2. 每轮保留独立 native root 和一次实验归属，由科研应用串行启动后继。首版使用真实本地 ORX toy；现有 preparation/training/evaluation 与训练 checkpoint 流程保持独立单轮回归，不声称已完成其多轮晋升。
3. 准入前持久化唯一后继意图和预算预留；并发 continue、丢失回执与重启都核对原请求，不能分叉或重置总预算。
4. 基线承接引用原候选源码产物、独立评估与内容身份。toy 没有训练 checkpoint，明确 sourceArtifact 类型；未来训练路径需独立 checkpoint 证据。
5. 第一版完成本地两轮；远程轮次在取得同样预算/原身份保证后再扩展。

## 验收

- [ ] 冻结一个 preset 的基线晋升、metric 方向、平局和停止规则，确定总预算归属。
- [ ] 真实 PostgreSQL/native Agno/受控进程及 evaluator 完成两轮，证明基线连续、模型/资源 pins 保留、用量累计而非重置。
- [ ] 并发 continue、后继准入回执丢失、预算预留与关联持久化之间重启，均只产生一个后继和一个原始请求。
- [ ] 总预算/截止时间耗尽、成员或资源撤销、前轮 UNKNOWN 未解决时，没有下一次效果派发。
- [ ] 实际浏览器查看谱系、评估来源、剩余额度与停止原因，重载后恢复持久状态。
- [ ] 现有单轮科学执行、保留基线、checkpoint、取消与用量回归通过；实际外部模型/算力另行取得运行证据。

独立评估继续作为基线晋升依据，UNKNOWN 资源收尾仍需正向结果。Agno 继续执行任务，本项不创建第二套通用队列，不扩展并行超参搜索或无限循环。

## 顺序与待定项

采用 #98/#99 关闭和显式服务归属，独立 round roots 通过 activity allocation 共享承诺，不增加 activity 父任务或扩大通用上限。活动预留全轮 cap，轮内独立 ledger 账户记实际用量，停止和用量证据齐全才一次结算；活动账户不再逐 attempt 双 hold。BYOK 无计量的 token/money 明确 unavailable/unknown，只执行有证据的 round/tool/deadline 硬边界。

首 preset 为新 `local-orx-toy-iterations-v1` recipe。源码 `orx_toy/evaluator.py` 的 MSE 越低越好，`comparison_contract.py` 使用严格 delta>minimumImprovement，选择 threshold=0：第一轮 16→0 晋升，第二轮实际使用前轮 candidate 作为 baseline，0→0 平局保留基线并停止。

当前 TaskLocalORXProvider/Adapter 没有 baseline_source 接口，ensure_experiment 固定复制 TOY_FILES；必须新增受信任 recipe revision 的源码 pin 输入，不能改写旧文件 hash 或伪称现接口已支持。scientific 三阶段 fixture 的 val_bpb=4.0 不是上述 toy MSE 证据。自动继续受成员明确总预算与策略约束，无新增管理员审批。真实两轮验证已完成：16→0 后使用前轮候选原字节执行0→0并停止。每轮仍需原生HITL。三阶段训练checkpoint、OS强制崩溃与真实外部供应商不在本次证据内。

验收记录：[verification](../../openspec/changes/link-bounded-research-rounds/verification.md)。启动已审核本地工具链时可显式传 `scripts/start_orx_local.py --iterations`；普通单轮配置不会自动启用。
