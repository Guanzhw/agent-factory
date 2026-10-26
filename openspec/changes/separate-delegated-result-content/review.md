# 独立审查

审查者：`/root/audit_crosscheck`；非方案/实施作者，仅写本审查文件。旧审计结论和旧 PASS 不替代本次精确范围审查。

当前结论：**实现 PASS**，截至 `342028fa3d182eee57c8873a992a400a02972b1f`；下文保留最初 NEEDS_FIX 与整改链。

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

## 正文深度方案增量复审 — PASS

精确范围 `0299819b965723868d910bb21fb55de2155bdef6` → `7c16722d7d736241267fcf1dc42a56ab14cc1a27`，4 个规范/审查文件，产品与测试源码未变。已核对新增的根深度 0、object/list 值递进、最大 64 的单一正文结构规则；producer/reader 共用该规则，65/500 层只在正向停止之后转 INVALID 并闭合，64 层完整往返。它为既有递归复制预留空间，原旧合同最多 6 层的已闭合正文不受影响，无新 catch/恢复层。

该最小整改方案可实施。仍须修后完整实现复审，当前未授予最终代码 PASS；必须看到 64/65/500 的实际 custody/effect 结果，不能只测独立 helper。

## 修后完整实现复审 — PASS

- 精确累计范围：`62614177c23c4d2cd0caf6b7c91418e74fde8ad4` → `342028fa3d182eee57c8873a992a400a02972b1f`。在前次完整 19 文件审查基础上，核对全部规范、生产、测试与新增证据增量；最终仍只有 `delegated_operations.py`、`workflow_contracts.py` 两个产品文件。未新增正文读取/恢复层或 Research 产品代码变化。
- 本次生产整改只有共用 `data(item, depth=0)` 的 `depth <= 64` 和两处递归参数；producer 与 reader 同规则。先前 500 层复制错误在进入 observation deepcopy 前已成为 `DELEGATED_RESULT_INVALID`，正向停止后实际 closed=true/effect DONE；64 层全文往返。原 UNKNOWN 分支在正文检查前保持不闭合，没有新增宽泛异常捕获。
- 独立执行：在上述精确 head，以共享 Python、`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=platform:platform/tests:applications:applications/tests` 运行 `python -m unittest test_delegated_content test_workflow_contracts -v`，**14 tests / 0 skip / PASS**。覆盖真实 SQLite custody/effect、64/65/500 边界、正常正文、原 wait、预算等号/超限、无损类型、非委派/metadata 反例和未知子树。`git diff --check 62614177..342028fa` 通过。
- 已核对作者新增首败/修后深度 JSON 与日志、52 项便携 PASS；旧首败尾空格已清且错误文本保留。作者报告静态/架构重验 PASS。原 6 项真实 PostgreSQL/native 回执仍精确属于 `803c00a0e7158830b6fedaa2b8496222cdac30e6`；本次没有重跑 PG，且 README 已明确。其实际 child result 是 string，新增结构递归边界不改变该受测分支；不把这一事实伪写成最终 head 的新 PG 实测。
- 结论：本轮已发现的完成阻断已整改，未发现剩余阻断项，授予上述累计代码范围 **PASS**。这不替代 coordinator 的组合检查、依赖审计、发布判断或真实模型/GPU/SSH/多主机验收。review 记录本身之后的纯文档提交须登记，不视作未审生产增量。

## 证据收敛增量复审 — PASS

精确范围 `da9e3cf9e530d0ba5a12c3587a5c4be8211c19ae` → `e64fe7061068d1d280b956fb7ad6a09dac995d5f`，仅 evidence README 与 5 份原始文本日志的移除。已逐文件比较 `/workspace/audit-remediation/c1-raw/` 与前一提交原字节，全部相等；4 份结构化 JSON、产品与测试均未变，历史日志仍可按 README 的精确提交恢复。文档保留失败、整改、通过、PG 所属旧源码及未重跑边界，`git diff --check` 通过。本增量 PASS，不增加任何运行验证声明。
