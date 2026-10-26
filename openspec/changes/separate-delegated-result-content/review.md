# 独立审查

审查者：`/root/audit_crosscheck`；非方案/实施作者，仅写本审查文件。旧审计结论和旧 PASS 不替代本次精确范围审查。

## 方案审查 — PASS

- 基线：`62614177c23c4d2cd0caf6b7c91418e74fde8ad4`。
- 方案 head：`114391f1906242e4d0eae3f8c305773d5c807dcf`。
- 实际完整范围：该 change 的 `.openspec.yaml`、proposal、design、spec、tasks，5 文件；无产品代码或测试变动。已对照生产 `DelegatedOperations`、RuntimeObservation、OperationCustody、WorkflowControl、Research results/context/evidence 和 application budget schema。
- 结论：本方案可实施。只对精确 native-delegated adapter/revision 的固定 output 中 `result` 使用正文合同，保留原 inline 形状和消费者，较新增引用/读取/恢复层更小。控制 envelope、其他适配器、原身份与停止证明没有被正文例外放宽。
- `budget.outputBytes` 在既有 v1/v2 schema 均为 1024..1048576；方案明确将其用于最终结果的紧凑 UTF-8 JSON 字节，属于明确的结果容量规则，而非声称过去已经在所有 native 最终正文处执行。producer 用原 child plan，reader 用 schema 绝对上限；旧已闭合小正文不按后来配置重新分类。
- 真实超限或非 JSON 的分类仅在正向 allStopped 后发生，使用原 FAILED/failure/effect 路径；不裁剪后当成功，不把格式错误继续当未知，不吞 owner/stop/DB 错误。原 native 结果保留。部署回滚不能让旧 reader 接管新正文，方案已如实记录兼容边界。
- 现有消费者仍读 `output.result`，没有新增未接通引用；spec 包含原 wait、本轮/前轮 Research 的完整等值验证，以及非委派反例、未知子树、预算等号/超一字节、原暂停/重启/继续一次的证据要求。

实施复审重点：严格检查 JSON 无损类型（尤其非字符串对象键、tuple、非有限数、循环/不可编码对象）；确认正文未被外层 32 KiB 再次计入，metadata 限额仍生效；超限停止结果实际闭合 effect，原 child 不重派；保留真实 native 继续收到全文的回执。以上是已通过方案的验收细化，不增加新机制或审批步骤。

本 PASS **仅为方案门槛**。未审实现、未运行新测试或 PostgreSQL，不代表最终代码 PASS。实施后的完整 `base..head`、失败基线与修后证据必须另行复审；PostgreSQL 时隙由 coordinator 安排，任务勾选归 coordinator。

## 实现首审 — NEEDS_FIX

- 本次完整范围：`62614177c23c4d2cd0caf6b7c91418e74fde8ad4` → `0299819b965723868d910bb21fb55de2155bdef6`，19 文件；已读 2 个生产文件、全部测试/规范/证据变化。源码实现提交为 `803c00a0e7158830b6fedaa2b8496222cdac30e6`；其后仅增加 PG 回执/README，没有继承成未审代码 PASS。
- 普通正文修复保持 2 个产品文件，接线最小。已检查作者首跑 4 subtest 的原 `WORKFLOW_CONTRACT_INVALID`、50 个便携测试 PASS、6 个真实 PostgreSQL/native 测试 PASS 的日志及测试断言。PG 证据覆盖 >32 KiB 原 child 正文、原暂停/硬重启/继续、最终全文等值、effect DONE、原 allocation SETTLED；模型仍为 deterministic fixture。本 reviewer 未重复运行 PG。
- **需修：正文验证与后续复制的结构能力不一致。** `delegated_result_bytes` 可接受 500 层嵌套 list 的有效 JSON；其 UTF-8 编码仅 1006 字节，远小于测试原预算 65536。但 `validate_runtime_observation` 最后的 `deepcopy(value)` 触发 `RecursionError`，被转成 `WORKFLOW_CONTRACT_INVALID`。producer 已走过“格式失败则 FAILED”的分类位置，导致实际原 custody 仍 `closed=false`、effect `UNKNOWN`。这保留了一个与方案承诺相反的完成阻断；不是安全漏洞或 PostgreSQL 故障结论。
- 独立窄复现直接使用本提交 `DelegatedContentTests` 的真实 SQLite custody/effect：将 `content='leaf'` 连续包装为单元素 list，再依次 `original()`、`completed(content)`、`service.lookup(...)`。深度 100/250/400 分别为 206/506/806 字节，均 COMPLETED/closed=true/DONE；深度 500 为 1006 字节，得到上述 ValueError/closed=false/UNKNOWN。测试只替换 child stop facts，不运行 native child。
- 期望整改：先明确正文结构支持边界，并让 producer 与持久化读取共用同一规则，确保不能安全表示/复制的已停止结果进入明确 INVALID 闭合；或证明完整复制路径可处理所承诺的所有结构。不要在多个消费者追加 catch、吞数据库错误或新增恢复框架。补边界成功、超界失败闭合和原未知仍 held 的回归；修后再审精确新 head。
- 文档小项：`git diff --check` 指出 `evidence/before.txt:1` 有尾空格。可去掉日志行尾空白，保留原失败文本和首跑证据。

当前结论为 **NEEDS_FIX，未授予最终实现 PASS**；其余已检查普通正文/元数据/消费者路径暂未发现阻断项。原方案 PASS 是历史方案阶段事实，不能覆盖本次实现发现。
