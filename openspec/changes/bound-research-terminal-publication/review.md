# 独立审查

审查者：`/root/audit_crosscheck`；非方案/实施作者，仅写本审查文件。本次不沿用旧 PASS。

## R1 方案审查 — PASS

- 基线：`62614177c23c4d2cd0caf6b7c91418e74fde8ad4`。
- 方案 head：`673313df24f3e9b37e9fae34f093c113c213863c`。
- 完整范围：本 change 的 `.openspec.yaml`、proposal、design、spec、tasks，共 5 文件；没有实现/测试变化。已对照 core 内容 API/授权/制品、Store 事务、observer 完成顺序、Research finalizer/消费者与组件 pin 装配；`git diff --check 62614177..673313df` 通过。
- 结论：本 R1 方案可实施。`contentArtifact` 是现有 content 的独立正文载体，复用原制品、同一内容授权和事务；不新建恢复/存储层。core 读取统一还原原 content 对象，比让各应用消费者分别解封更小。协调者已确认 `application_content.py` 及必要测试/API模型归本 R1 作者。
- 前期方案将“20 个合法精选证据 + 内部第 21 个正文制品”分类为 publication_failed，存在正常组合缺口，已在正式方案纠正：正文与 20 精选附件独立。正式 spec 将该组合列为正向验收，并将真正的配置字节预算不足单独处理。
- 旧 inline 请求移除新增 None 字段以保留 fingerprint；引用正文保留对象/结构/安全数据校验、精确 owner/task/hash 和 raw/规范 JSON 单体预算。`_readable` 后解封，损坏或来源撤回不返回影子正文。list 明确仍有分页及单体上界，没有声称模型上下文扩大或所有大记录均送入模型。
- 原完成事务覆盖制品及事件、publication、领域终态与 settlement；仅确定正文尺寸超限允许 `publication_failed` 收尾，原 scientific outcome/decision/selection 不改，自动后继不发。其他权限/哈希/数据库错误保留原回滚语义。需避免把确定超限状态写成“科学失败”或“完整成果已发布”。
- 原恢复边界具体：从冻结基线独立构造 `ResearchWorkflow().registration`，使用真实 `_configuration` 与 `digest` 重算，确认为 `workflow/research-round/1/2c1fcb5650d8473d2171f6d374035b8d4db452b53603337e2b13f3b43f661c54`。仅此旧 pin 获完成 callback，不注册旧执行器/自动 reconcile，不按名称通配未知旧版本。
- QA/关联/前轮 context/peer source/delivery/UI source 均已列入消费者验证。R2 多轮聚合仍是下一项独立缺陷；本 PASS 不把 R2/R3/R4 或整体产品验收提前记成完成。

实施复审重点：互斥 API 与旧 fingerprint 实测；20 证据加长正文的完整等值往返；来源撤回、制品损坏/缺失；写制品后及写 publication 后故障均回滚且重试仅一份；旧已停止 pending finalization 的真实 terminal/settlement 收尾；旧 paused 不使用新执行器。正文载体必须不混入精选证据或被下游重复导出。只读故障、数据库错误与预算不足应保持可区别。

本 PASS **仅为 R1 方案门槛**。未审实现、未运行新测试、PostgreSQL或浏览器；后续须按实际完整 `base..head` 和失败/修后回执重新审查。重 PG/浏览器时隙由 coordinator 安排，任务勾选归 coordinator。
