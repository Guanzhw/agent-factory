# Design

## Context

动机见 proposal.md。工作树基线 b50d196 包含 #97 的只读 GET 与后台收尾，不包含 #99 服务图重构。

- application_schema.py 已严格区分 v1 与 v2；v2 使用 configSchema/config 与 operationSeconds。composition.py 保留 contractVersion、完整 inputSchema/inputValues 和 applicationConfig，但计划没有完整应用定义及 configSchema。
- remote_handoff.py 的 plan_manifest/_manifest 使用 `{plan, sha256}`，sha256 是 digest(plan)，现有 PLAN_KEYS/BUDGET_KEYS 及配置 reader 为 v1。TrustedHandoffClient._target 比较 digest(plan)；remote_usage 的 grant 把 manifest_hash 用作 expected_source_plan_sha256；receiverBindingProof 也保留该身份。
- remote_authority.py 的 AuthorityBudget/AuthorityScope 与 remote_handoff.py 的 _authority、authority_callback 都需要版本感知；只改 wire reader 无法使恢复链路接受 operationSeconds。
- remote_bindings.py 保持源计划与导入计划之间的严格对应。factory_api.py 的 GET /execution-targets 当前仅返回目标身份与 connectivityVerified=False。

## Goals / Non-Goals

**Goals:** 在既有权限、材料、执行绑定和停止证据约束下，使中性 v2 根任务经过真实远程队列完成；定义与输入不丢失，原操作恢复不创建第二次效果。

**Non-Goals:** 不扩展 workflow、scientific、delegation、嵌套远程 placement、任意第三方协议兼容或集群调度；不修改 v1 字节/hash，不借本变更引入 #99 graph，不扩张管理员权限，不放宽 UNKNOWN 或时间限制。

## Decisions

### 1. 独立严格 v2 envelope，保留 plan hash

v1 仍为 `{plan, sha256}`。v2 为 `{wireVersion: 2, plan, applicationDefinition, sha256}`，外层 extra keys 拒绝，wireVersion 与 plan.contractVersion 严格整数 2。sha256 仍等于 digest(plan)，不是整个 envelope 的摘要。完整 applicationDefinition 用既有 ApplicationService 的版本 hash 算法核对 plan.applicationRef.sha256，因此经 plan 内 pin 间接绑定。

拒绝改成 envelope hash：这会改变 _target、sourcePlanSha256、usage grant 与 receipt proof 的既有含义，需额外迁移且没有本项消费者收益。也拒绝只发送接收端可变名称引用：它不能证明原 schema/config。完整定义同样受既有 wire 大小上限约束。

导入边界复用应用 schema 与 composition 的语义约束，验证选择 mode、材料/绑定、定义 configSchema/config、inputSchema/inputValues 与计划的确切对应；不能只验证 definition 自身合法而忽略 plan 值被替换。接收后内部执行继续使用既有契约，不在每个 callback 重复解析整个 envelope。

### 2. 静态目标声明加 receiver 实际校验

HandoffTarget 增加 supportedApplicationContracts，缺省 `(1,)`；receiver 的可信来源/接收配置独立显式启用 v2。GET /execution-targets 返回声明值，connectivityVerified 保持实际含义；不增加网络探测或静默协商降级。声明只能提前说明限制，prepare 仍检查 receiver 配置、runtime/bindings 和材料。

默认 v1 target fingerprint 保留旧算法/结果；仅显式 v2 opt-in 的规范化配置增加版本声明参与 fingerprint。恢复继续使用持久化原 target/authority 身份；配置变动不能把原操作重新指向新目标。关闭 opt-in 阻止新接收，已有操作按原身份观察/取消；需要当前权限的执行动作仍 fail closed，不能以兼容恢复绕过撤权。

### 3. 预算按原版本选择严格分支

remote_authority 的预算模型增加严格 v2 分支，含 operationSeconds、无 experimentSeconds；保留 v1 原响应形状。版本选择来自已验证的原计划，不通过某个时间字段是否存在猜测版本。authority scope、回调、authority recovery、receiver 导入预算检查全使用同一版本选择规则；混合预算、扩大预算、原 plan hash 不符继续拒绝。

不得把 sourcePlanSha256 换成 envelope hash，也不新增仅为迁移而存在的身份字段。remote_bindings 比较时保留 contractVersion、schema、输入和配置，不能为了接收 v2 放宽 unrelated 原绑定检查。

### 4. 选定中性 runtime，范围先收窄到根任务

验收使用现有 demo_v2_definitions 的 checksum-neutral、local-synthetic-model-v1 与 native-checksum-v1；它们提供确定性原生执行和准确 checksum 产物。增加测试发布变体：非空但无权限意义的 configSchema/config 与 inputSchema/inputValues，使用受信任测试 adapter 记录收到的值与 operationSeconds，避免空配置让漏字段测试假通过。core 不导入科研实现，fixture 在测试装配层显式安装现有 bindings。

允许受支持的 native agent 根任务，显式拒绝 workflow nativeComponent、scientificEnvelope、delegation、非根深度、已有 remoteHandoff 与嵌套 placement。通用 schema 支持不意味着每个 runtime 都能远程运行；receiver bindings 与实际配置校验继续决定可执行性。

### 5. 不分叉生命周期与恢复

prepare/dispatch/receipt、重复请求、原 operation id、native identity、usage/proof 与停止证据继续走现有实现。v2 只扩展不可变数据与预算版本；不增加重试派发许可。#97 GET 只读、后台无 GET 仍可收尾、取消范围和 held/UNKNOWN 规则作为回归约束。

## Risks / Trade-offs

- 完整定义与计划各自合法但互不一致 → 负例逐项篡改 definition、mode、schema、input、config、绑定与 hash，必须在效果之前拒绝。
- v1 默认 target fingerprint 被新增默认字段改变 → 固定旧指纹和旧 manifest hash 回归；仅 v2 opt-in 纳入新配置。
- authority 仅首次 prepare 支持 v2、重启回调仍按 v1 → lost-ack 与重启测试覆盖持久化后的真实 callback 和权限撤销。
- 静态能力可能过时 → 显示声明而非连通性承诺，receiver prepare 保持最终校验。
- 两进程测试成本与并发干扰 → coordinator 串行运行真实 PG/process，worker 仅便携测试；按独立行为矩阵复用 fixture，不放宽 deadline。

## Migration Plan

先落冻结 v1 的契约负例和 v2 reader/authority，再显式配置选定 receiver 与目标，最后连接目标展示和真实集成。默认配置仍仅 v1，无旧记录批量改写。回退时停用新 v2 接收并保留能读取原 v2 操作的代码直至收尾；不得用不认识 v2 的旧 reader 强行恢复已有 v2 操作。

当前仅完成规划，未实施或运行上述行为验收；各阶段实际命令、结果与限制由 coordinator 记入 tasks 和计划文件。
