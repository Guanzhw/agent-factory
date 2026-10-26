# 独立审查

审查者：`/root/audit_crosscheck`，非实施作者，仅维护本文件。R1 已审实现不替代本次方案或后续代码复审。

## R2/R3 合并方案首审 — NEEDS_FIX

- 精确范围：R1 基线 `d9f92acffcfd6937c4c43ad8c3ddc205e6e1b9f6` → 方案 head `26e63f94e712aa50a6d73c432c8c1f62b528a50e`，5 个规范文件，产品/测试未变。coordinator 已授权把同一交付快照的 R2/R3 合并。
- 聚合方向可行：原身份快照替代完整正文副本、统一 UTF-8 manifest/精选证据/实际 ZIP 上限、保留两阶段创建和事务外组包，均复用现有合同。R3 保存原 ending/owner、旧行不补造历史、remainingQuestions 不声称原文缺失，范围合适。
- **需补 ending 的既有来源保护。** `projects._protect` 根据 `peer_sources.project_dependencies(projectId)` 隐藏 ending，而现有 delivery 的 sourceIds 只来自已发布 terminal records。某轮已经消费 peer、但尚未终态或因授权撤回没有 publication 时，它的依赖不会由 recordIds 推导出来。新增原 ending 正文若沿用这些 sourceIds，可在项目详情已经隐藏原文时从新成果取回；这不是假设任意外部攻击，而是新增载荷遗漏现有来源合同。
- 最小修订：在同一创建 snapshot 中，将原 ending 所受的完整 project_dependencies 纳入不可变 sourceIds，并沿现有 current-source 校验复核；依赖正文不因加入 sourceIds 成为选中导出记录。新旧成功请求仍固定原快照，不在读取旧交付时动态追加当前项目依赖或 ending。补“未发布轮依赖 + ending”的正向与撤回 create/read/download/list 反例。

当前 **NEEDS_FIX，尚未放行实施**。无需新授权/存储/恢复层；提交精确方案增量后复审。

## R2/R3 修订方案复审 — PASS

- 精确累计范围：`d9f92acffcfd6937c4c43ad8c3ddc205e6e1b9f6` → `951e0e1f2344d86ba9aee8667f9906d56755078b`，5 个方案文件及本历史 review；产品和测试仍未改变。已重读全部方案及两次整改增量，`git diff --check` 通过。
- 首审的未发布轮依赖遗漏已明确整改：新 ending 记录创建时原 `project_dependencies` 身份子集，顶层 sourceIds 保存它与所选记录依赖的完整并集；创建及提交、read/download/list 均复核。旧交付不读当前项目补造历史；依赖-only 正文不导出，当前交付 owner 也须有效。
- 第二次窄反例进一步修清现有语义：`core content.read` 允许来源作者读自己的 personal 记录，而 `ResearchPeerSources.require` 对项目依赖要求 team。现在仅 `ending.sourceIds` 这个固定原子集额外检查 team，覆盖同 owner 撤回；普通 selected records 保持原 owner/personal 可读合同，不把所有来源一律收紧。无需新权限层或依赖当前可选服务是否安装。
- 聚合/预算与消费者接线可实施：复用一个完整包边界，UTF-8 manifest 一次计数、只导出明确精选证据、包括实际 ZIP 头部；同一快照读取原字节、事务外组包，提交前复核原目标与固定全部来源，失败不留新 delivery/receipt。原 records API 与 UI 全文保持，旧含副本行从原身份重建，ending 原文/owner/版本/时间/清理事实不推断、不裁剪。
- **方案 PASS，可开始失败回归和最小实现。** 实现仍须独立按精确完整 `base..head` 复审；重点核对两条合法长记录、R1 中文外置正文加 20 精选附件、实际 ZIP 等号/超界、旧格式/重复请求、未发布轮与同 owner 撤回、普通 personal 正向、owner 停用、两阶段创建来源变化，以及 UI 完整 ending/无快照表述。不要把本 PASS 或 R1 的 PG 回执记作 R2/R3 已运行证据；PG 时隙仍由 coordinator 安排。

## 基线等价与未发布轮分类增量 — PASS

新工作树基线 `e4afcb6eb230ad079f13ac87dc5e3d581701b390` 只在 R1 已审产品上补原 reviewer 文档及 coordinator 任务勾选。新 spec `103ec594396010f97f20b1ed15aca49e0f9f376d` 与上述 `951e0e1f` 的 R2/R3 方案目录完全相同；原方案 PASS 适用于该等价内容。

另审 `103ec594396010f97f20b1ed15aca49e0f9f376d` → `244a9d63b984802eeea8c304c8fb2af2c9c7dfd8` 的 3 个文档文件：补充 terminal 已存在但没有 terminal_record 时的 `round_not_published:<id>` 缺证标记，与原 `round_not_terminal` 互斥；已有其他正常记录也不能掩盖这项缺失。旧交付仍保留原快照，不动态回填，不补造正文或改科学结论。该小项方案 PASS，可实施；这次未审工作区中正在进行的其他产品实现，代码仍待完整复审。
