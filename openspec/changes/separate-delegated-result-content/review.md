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
