# 独立审查

审查者：`/root/audit_crosscheck`，非实施作者，仅维护本文件。R1 已审实现不替代本次方案或后续代码复审。

## R2/R3 合并方案首审 — NEEDS_FIX

- 精确范围：R1 基线 `d9f92acffcfd6937c4c43ad8c3ddc205e6e1b9f6` → 方案 head `26e63f94e712aa50a6d73c432c8c1f62b528a50e`，5 个规范文件，产品/测试未变。coordinator 已授权把同一交付快照的 R2/R3 合并。
- 聚合方向可行：原身份快照替代完整正文副本、统一 UTF-8 manifest/精选证据/实际 ZIP 上限、保留两阶段创建和事务外组包，均复用现有合同。R3 保存原 ending/owner、旧行不补造历史、remainingQuestions 不声称原文缺失，范围合适。
- **需补 ending 的既有来源保护。** `projects._protect` 根据 `peer_sources.project_dependencies(projectId)` 隐藏 ending，而现有 delivery 的 sourceIds 只来自已发布 terminal records。某轮已经消费 peer、但尚未终态或因授权撤回没有 publication 时，它的依赖不会由 recordIds 推导出来。新增原 ending 正文若沿用这些 sourceIds，可在项目详情已经隐藏原文时从新成果取回；这不是假设任意外部攻击，而是新增载荷遗漏现有来源合同。
- 最小修订：在同一创建 snapshot 中，将原 ending 所受的完整 project_dependencies 纳入不可变 sourceIds，并沿现有 current-source 校验复核；依赖正文不因加入 sourceIds 成为选中导出记录。新旧成功请求仍固定原快照，不在读取旧交付时动态追加当前项目依赖或 ending。补“未发布轮依赖 + ending”的正向与撤回 create/read/download/list 反例。

当前 **NEEDS_FIX，尚未放行实施**。无需新授权/存储/恢复层；提交精确方案增量后复审。
