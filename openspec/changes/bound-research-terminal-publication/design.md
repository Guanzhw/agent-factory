## Context

基线与复现见 proposal。`ApplicationContent` 已拥有当前成员/全部 sourceContentIds 授权、原 artifact owner/hash 校验及不可变 publication。`Store.artifact_write` 只写 `af_artifacts` 与事件表，借用 `Store._connection`；没有文件系统副作用，也不因 task 已标 terminal 而拒绝。Research finalizer 在 core 完成事务内已有准确 owner/task/run，故可复用该公开 store 写口。

## Goals / Non-Goals

修复 R1 并让旧已停止的大决定可原位收尾；正文与科学证据均完整。R2 多轮 manifest 全文复制、R3 ending、R4 新准入分别后续小变更；本次不建立后台修复器、不续跑旧组件、不改 Agno 或全局限额。

## Decisions

1. **单条合同。** `ContentPublication` 增加可选 `contentArtifact: ContentArtifact`；与 `content` 对象互斥。省略引用时从标准化值移除该 None 字段，旧 fingerprint/回执不变。内联仍使用原 16384 字节转义 JSON 合同；引用正文必须是 UTF-8 JSON 对象，通过原有限深度/节点/字段/字符串及 `_safe_data` 校验，字节数按 `ensure_ascii=False` 规范 JSON 不超过 `settings.experiment_output_bytes`（默认 65536），原制品字节也服从该上限。只给 `bounded_json` 增加默认不变的编码选项，避免复制结构验证器。
2. **读取合同。** publish 读取并验证精确 owner/task/artifact/hash 及正文，存引用而不再存完整影子正文；read/list 的 `_readable` 成功后读取并解封，返回原 `content` 对象。contentArtifact 的原制品读取也使用该 publication 的当前来源授权。精选 `artifacts` 仍仅为原最多 20 项，正文引用不占其额度。list 的 route 上限仍为 100，单次正文上界为 `limit × 单正文预算`，默认约 6.4 MiB；不另建缓存。损坏/缺失返回明确 409/404。
3. **原完成事务。** Research 在 `_finalize` 形成原完整 body，内联可表示就走旧路径；否则在真正单正文预算内调用 `Store.artifact_write(task.run_id, ..., metadata=原 application 输出 provenance)`，再以 contentArtifact 发布相同 sourceContentIds。只写原 task 制品，不授权访问新资源。一次 transaction 包括制品及其事件、publication、round terminal、任务 terminal 和 settlement；故障向外传播全部回滚。提交后现有 round.terminal 幂等短路避免新写入。无需新增 request 状态、扫描器或文件清理器。
4. **真正超预算。** 在制品写入之前检查规范 UTF-8 大小；超出既有单制品预算时持久 `sharing=publication_failed`、`continuationBlocked=RESEARCH_PUBLICATION_TOO_LARGE` 和尺寸/上限。原 decision/outcome/goal/selection 不改不删，owner 仍经来源保护读取；终态描述实际已停止与发布失败，不能把它当科学失败或成功交付。UI 明示发布失败。DB/权限/哈希等非该确定大小错误继续回滚，不 blanket catch。
5. **旧停止任务。** 基线 Research 精确 pin 为 `workflow/research-round/1/2c1fcb5650d8473d2171f6d374035b8d4db452b53603337e2b13f3b43f661c54`。装配为此 pin 声明仅原 `finalization_context` 责任，复用当前修复后的 finalizer；新研究仍只使用当前 pin。不给旧 pin 新 native executor、observe/reconcile 或新准入，旧 paused workflow 仍需原代码执行/原 core 取消。只支持该明确受影响格式，不按 workflow 名称通配未知版本。
6. **实际消费者。** core 返回内容语义不变，所以 `ResearchRounds.context` 前轮内容、`ResearchQA._source/_select`、`ResearchAssociations.prepare/context/for_round/round_inputs`、`ResearchPeerSources` 依赖读取、`ResearchDelivery` 取源及 `assistantApi.source → /application-content/{id}` 均消费完整正文。QA/关联 16 KiB 上下文保持；超上下文记录按既有规则不进入模型，不能称为已消费。验证至少一个超过 inline 转义限制、但 UTF-8 包含封装后可放入模型上下文的中文记录。
7. **后续组合合同。** R2 使用不可变 recordIds/sourceIds 作为 manifest 存储，read/UI/download 解封原记录；完整 UTF-8 manifest（正文一次）+精选附件+ZIP 开销共同受既有 delivery 上限约束，真超限为 413，不半包、不导出正文载体第二份。此处冻结接口衔接，本 R1 不宣称已修好 R2 的 aggregate 500。

原 record refs 本身无法存放当前单条超限终稿；拆成多个 publication 会新增正文拼装、来源图与候选检索污染。应用专用解封则需改变多个消费者及 UI 路由。一个明确的正文引用字段复用已有授权与制品生命周期，改动更小；提高所有 content 上限、截断或拆开完成事务均不采用。

## Risks / Trade-offs

- 引用读取需多一次数据库制品读取 → 保留原分页、单体字节与结构界限，测多条列表；无文件/网络读取。
- 核心接口扩展可能影响旧 fingerprint/内容安全检查 → 旧发布重试、混合格式、恶意正文/双字段、撤回/损坏与 20 附件正向用例为必要回归。
- 新源码 pin 变化 → 上述旧 pin 仅收尾的声明与真实 PG 已停止任务恢复一并验证；不声称升级可续跑旧暂停步骤。

## Migration Plan

无需表迁移或回填。先失败回归，再实现并验证新旧正文读取及事务回滚。部署前独立完整 diff review；真实 PG/浏览器通过 coordinator 串行时隙执行。回滚代码不破坏已有制品/记录，但旧代码不能完整解封新引用正文，因此不能把回滚当无影响操作；保留已发布数据，不删除。
