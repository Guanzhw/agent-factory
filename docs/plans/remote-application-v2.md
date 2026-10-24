# 规划：通用 v2 应用的远程执行契约

状态：Draft 实现；确定性两进程/PG协议验收已运行，本地静态/Web/原v1回归已完成，精确CI待提交。原规划基于 PR #95 `246f06541b21915392a77555e24f3f617d34de9f`；本次设计基线为独立工作树 `b50d196`，已包含 #97 `965350f`，不包含 #99 服务图重构。
OpenSpec change：[support-v2-remote-application-handoff](../../openspec/changes/support-v2-remote-application-handoff/proposal.md)，实施与所有权见 [tasks](../../openspec/changes/support-v2-remote-application-handoff/tasks.md)。

## 问题与结果

成员应能将一个受支持的通用 v2 应用交给远程 receiver，同时保留本地执行的不可变输入、绑定和预算。现有 v2 远程拒绝是文档明确的能力限制，本项扩展该能力。

- `platform/agent_factory/application_schema.py:82-100,127-153`：v2 使用 schema 验证的 application config 和 `operationSeconds`，v1 保留旧配置与 `experimentSeconds`。
- `platform/agent_factory/composition.py:225-226`：本地计划保留 v2 标记。
- `platform/agent_factory/remote_handoff.py:34-38,163-170,194-211`：远程导入只接受 v1 及其固定字段。
- `docs/APPLICATION_DEVELOPMENT.md:119-136`：记录 v2 本地支持与 `REMOTE_CONTRACT_UNSUPPORTED` 的远程限制。

## 实施范围

1. 为一个选定的中性应用/runtime 冻结 v2 wire contract：schema/input/config、执行绑定、操作时间、产物来源与 receiver 支持声明。
2. 保留冻结的 v1 reader；v2 在真实 wire 边界验证一次后归一化到共享内部执行契约。
3. prepare、dispatch、恢复、继承、取消和产物读取全程保留原版本、内容身份与原回执。
4. 未支持的 receiver 明确拒绝；目标页面展示已知能力限制。已有 prepare 或未知回执按原请求核对。

## 验收

- [x] 两个真实服务进程与独立 PostgreSQL：发布一个 v2 应用，准备、派发一次，通过 native receiver 完成并读取状态、事件及准确产物字节。
- [x] 丢失 prepare/dispatch 回执、并发重复派发、receiver 重启和取消前后，都保持原身份且不额外启动效果。
- [x] 执行 adapter 收到准确 v2 配置和时间上限；混合版本预算、错误 schema/input、未知版本在新效果之前拒绝。
- [x] 原 v1 handoff 与恢复回归继续通过；构建后的浏览器展示目标支持/拒绝状态。
- [x] 发布实际支持矩阵，将本地确定性协议验收与外部服务兼容性分别记录。

旧 v1 定义与 hash 不改写，版本不自动降级，UNKNOWN 不重放。本项不扩展集群调度或承诺任意第三方 receiver 兼容。

## 已选择的协议与支持边界

可独立于多应用装配实施。选现有 checksum-neutral 与 local-synthetic-model-v1/native-checksum-v1，在测试装配层使用确定性 native runtime；发布含非空 configSchema/config 与 inputSchema/inputValues 的测试变体，验证准确传输及 operationSeconds。首版仅 root native agent handoff，拒绝 workflow、scientific、delegation、已有远程 handoff 与嵌套 placement。

v1 保持 `{plan, sha256}`。v2 使用准确字段 `{wireVersion: 2, plan, applicationDefinition, sha256}`，wireVersion 与 plan.contractVersion 严格为整数 2。sha256 仍为 digest(plan)，不是 envelope hash；完整应用定义通过既有应用版本摘要算法核对 plan.applicationRef.sha256，间接绑定完整 schema/config。验证定义、mode、输入、配置、材料和绑定与计划一致，额外字段及混合预算拒绝。

目标 supportedApplicationContracts 默认仅 v1，v2 显式 opt-in；目标页面展示声明，receiver prepare 自行验证实际支持范围，无自动降级。默认 v1 target fingerprint 不变，仅 v2 opt-in 纳入新能力配置。authority 的预算模型、回调与恢复根据原计划版本选择严格分支，不改变 manifestHash/sourcePlanSha256、usage grant 或 binding proof 的既有含义。

详细调用边界与取舍见 [design](../../openspec/changes/support-v2-remote-application-handoff/design.md)。生产编辑与重型测试由 coordinator 分配和串行安排；实际分层结果和首轮失败见OpenSpec verification.md，不外推真实供应商兼容。
