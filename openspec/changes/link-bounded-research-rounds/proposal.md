# Proposal

## Why

研究记录 continue 目前只表达下一步意图，没有可靠串联后继轮次；独立新 root 又会重置任务预算。成员需要保留原基线与资源身份，在一个活动总承诺内串行完成可恢复、可停止的科研轮次。

## What Changes

- 新增应用拥有的 activity/round 谱系、唯一后继意图、绝对截止时间与总预算；每轮仍是独立 native root，不扩大通用 child/depth 上限。
- 采用活动预留全轮 cap、轮内独立 allocation 账户、正向停止与用量证据后一次结算；UNKNOWN 不退款、不启动下一轮。
- 首版选择现有本地真实 ORX toy 的版本化迭代 recipe：MSE 越低越好，严格改善晋升，平局保留基线并停止；第二轮实际读取前轮候选源码。
- 使用源码产物和独立评价回执建立基线 pin；toy 没有训练 checkpoint，不伪造 checkpoint 或科学结论。
- 展示轮次谱系、剩余额度、评价来源和停止原因。BYOK token/money 未计量时明确未知，只承诺真实计数支持的轮次、工具和截止时间硬限制。

## Capabilities

### New Capabilities

- `research-round-activities`: 共享总预算内的串行科研轮次、不可变基线晋升及恢复。

### Modified Capabilities

无已发布 specs；保留既有单轮执行、原生队列、只读 GET 与 UNKNOWN 规则。

## Impact

科研应用协调与装配、版本化本地 toy recipe、核心账本 local allocation 接口及对应 schema/UI。基线 48e642f 已合入 #99 7d0701f；不依赖 #100 远程 v2，不修改 #102 工具身份。只使用本地确定性输入、真实 ORX/Agno/受控进程与 PostgreSQL 验收，不调用付费或真实外部模型。
