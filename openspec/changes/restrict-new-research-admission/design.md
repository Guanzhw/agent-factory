# Design

## Context

基线见 proposal。命令表已有唯一 `(actor_id, request_id)`，action 区分 `research.start`、`research.round.start` 和 `research.round.resume`；旧首轮指纹 action 为 `start`，两类 round 指纹 action 均为 `round.start`，包含 project 与 expectedVersion。当前 start 按 supports(当前 agreement) 路由，错误地把“恢复哪条原命令”与“能否新建当前研究”混在一起。公共 install 无 Workflow 时也直接注册历史 ResearchRuns.start。

## Goals / Non-Goals

**Goals:** 公共新准入只有当前固定研究路径；原请求和历史只按持久事实恢复；前端可选项与后端能力一致。

**Non-Goals:** 不改变原 pin、旧数据库或预算；不新增兼容模式、历史 executor、finalizer 或跨版本迁移。不处理 R2/R3，也不借此重构原 operation/停止生命周期。

## Decisions

1. **先识别持久请求。** ResearchRuns 提供小范围共用原命令核对：明确接受 `research.start`（指纹 action=`start`）和 `research.round.start/resume`（指纹 action=`round.start`），仍按 owner/project/expectedVersion 核验完整 fingerprint。ResearchRounds._prepare 在既有事务内先复用此检查，有原命令即返回其 intent，无命令才执行当前新准入。action 来自持久表，不是客户端标记；其他动作或同 key 不同内容继续拒绝。
2. **历史服务仅保留实际恢复职责。** ResearchRuns._prepare 收缩为上述原 command 检查，不存在原命令时明确拒绝，移除新 scope/allocation/experiment/start-record 创建分支。将已有重复的 intent→receipt 处理共用：无 request 的旧 round.resume 直接回原结果；其余只用原 request/allocation 读取收据，无 task 时才交原 core 请求复核，ResearchRounds.start 复用同一处理。list/stop 和 rounds 使用的 _input_values 保留。这样无 Workflow 的公开 install 可恢复 legacy/round 原回执及原 resume 结果，但不能新增历史工作；不引入 `allow_legacy` 开关。历史测试用明确持久 fixture 构造旧 intent，不将测试历史种子当新产品入口。
3. **新准入检查留在原事务。** rounds._prepare 的无原 command 路径继续严格比较完整 `{kind,id,revision,sha256}` pin。availability 先识别已有未结束/同目标 round 或历史 experiment，返回原操作提示；只有可新建/续接的候选才检查当前 pin，非匹配返回 `RESEARCH_NATIVE_COMPONENT_REQUIRED`。读取旧记录不因旧 pin 不再安装而转入另一条执行路径。
4. **前端复用现有数据。** ExecutionEditor 增加 ownerId，通过现有 setupApi.candidates 取得 workflowPin，与应用 mode.nativeComponent 全字段比较。只列匹配应用/mode；原配置不匹配时保留说明并禁用提交，不默认选中替代项。ProjectDetails 展示清楚中文不可用原因；不新增查询 API 或通用策略工具。
5. **与 R1 串行整合。** R1 作者只修改 rounds 完成/发布和 public 中已知旧 pin 的 finalization-only 注册。R4 不改这些方法、注册或 Workflow 实现。R1 精确实现通过 review 后，由协调者更新本分支基线；作者与 reviewer 核对新基线差异后才加失败回归和产品实现。

## Risks / Trade-offs

- [旧 paused 对应代码缺失] → 新准入 gate 不阻断读取/原取消，但不提供旧 executor；缺实现的跨版本续执行仍未验证/不可用，测试不得将 pin 改成当前值。
- [未装 Workflow 的投影范围] → 保留项目约定历史、持久原 command 结果和 core 原 task 读取/清理；不声称该装配已经提供 ResearchRounds 列表/领域执行步骤。原 round command 可以返回既有 task 收据，原 intent 尚无 task 时仍须通过 core 原组件检查。
- [原意图无 task 恢复产生新 reservation] → 保留原 request/allocation，通过 core 原有唯一准入及当前 scope/授权校验；404、超时、重启不授权替代请求或 UNKNOWN 重派。
- [旧首轮创建测试变为历史测试] → 保留原 owner/幂等/原预算/UNKNOWN/取消断言，以固定持久旧数据验证恢复；新创建和事务回滚证据移到唯一 rounds 路径，不能只删除失败断言。
- [候选 API 不可用] → 配置页明确显示读取错误且不允许猜 pin；旧历史页面与原请求恢复不依赖候选 API。
