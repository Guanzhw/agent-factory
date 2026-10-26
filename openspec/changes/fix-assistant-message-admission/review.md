# C2/C3 独立方案与实现审查

Reviewer: `audit_quality`，非方案/实施作者；记录写在独立审查目录，作者分支不并发写入。

## 方案审查 — 2026-10-26

精确范围：`62614177c23c4d2cd0caf6b7c91418e74fde8ad4` → `9a740d327c25021a4b07f260eb3210dca77b2baf`，`/workspace/agent-factory-fix-message-admission`，change `fix-assistant-message-admission`；5 文件 +100 行，仅方案。

**方案 PASS，允许依此实施。此结论不是实现或运行验收 PASS。**

- 已读 AGENTS、ARCHITECTURE、development checks、现有消息/事件设计及真实 Store→message/event fresh gate。C2 只用明确 HTTP 429 + `ACTIVE_TASK_CAPACITY_EXHAUSTED` 分类暂时拥塞，复用 pending、公平批次和原 event/message/request/allocation；不引入重试框架，不扩大为所有 429 或任意 4xx 重试，范围合理。
- C3 把 recipient、sender、enabled 与完整 prepared 请求指纹前置，预算分支只承担 scope/caps/allocation；移除多余 owned 读取，原 task 早返回保留，职责更直接。无预算端点无需强制增加预算配置。
- 计划中的真实 Store 容量耗尽→释放测试能区分无 task 的待准入与已 reserved/UNKNOWN；准备窗口撤权和指纹冲突用例覆盖实际缺口。应保持“原身份、至多一次 native dispatch、已有 task 只观察”的断言，不能用新 ID 或降低断言通过。
- 明确保留历史 rejected 不迁移、真正终局无 task 的 hold 不释放，避免将该窄修复扩成结算或批量重派系统；交付时应保持此未解决范围说明。

实现 gate：收到具体实现 SHA 后检查 base→head 完整 diff、最小失败分类、当前授权与预算解耦以及原 UNKNOWN/清理边界；审阅原始首失败和修后回执。重型 PG 验证由 root 串行协调，不能以本方案 PASS 替代。

## 实现审查 — 2026-10-26

精确完整范围：`62614177c23c4d2cd0caf6b7c91418e74fde8ad4` → `f9fc6ae4fe2a952ce19c2568c4273dcaa0727a0c`，11 文件 +265/-9；其中3个产品文件合计 +9/-9。先行方案为上述 `9a740d3`，失败回归先行提交 `7945d10`。

**本精确候选代码/简洁性及已读取目标验收 PASS，无实现阻断。后续文档增量、整合与精确 head CI 需按实际范围核对，不等同发布/合并许可。**

- 已逐项审完整 diff。Store 只将实际容量429改稳定码；AssistantEvents 只对精确429+该码留 pending，LOCAL_BUDGET_EXHAUSTED 和错配409仍终局，状态更新保留原 admission fence。没有新worker、延时器、替代request或“任意429均重试”路径。
- AssistantMessages 移除多余 owned/无预算早返，共同 sender/recipient/resolve/完整 prepared 指纹只保留一份；scope/caps/allocation 检查仍在有预算分支。`Store.reserve_task:323`–`:338` 的原task命中仍先于 fresh gate，新检查不进入已有reserved/UNKNOWN的观察/恢复路径。
- 新PG容量测试确实先通过原 native bridge 创建两个占位任务，实际 Store 拒绝事件任务后检查 pending、原 allocation HELD、零第三次submit；释放原任务后，同一 event/message/request/allocation 生成一个新task，最后SETTLED且submit总数为3。没有用手改capacity counter或替换task假通过。
- C3测试在真实 `_prepare` 后暂停发送，提交端点/发送者禁用后恢复；公开请求必须拒绝，native submit为零且message保留。另一公开实例用例核对错误plan及完整fingerprint。既有UNKNOWN用例新增recover后仍零submit，原断言、期限未放宽。
- 已实际读取作者保留的 `baseline-portable.log`（1 test、2 subtest failures）和 `baseline-postgres.log`（4/4 FAIL、0 skip）：分别出现rejected≠pending、禁用后202、sender禁用仍submit、错误plan仍202。首失败未被改写或删除。
- 修后日志实际终态：`fixed-portable.log` 19/19；`fixed-portable-related.log` 20/20；`fixed-postgres-targeted.log` 4/4、9.060s；`fixed-postgres-suite.log` 31/31、70.515s，均无skip。读取 Ruff PASS、Pyright 0 errors/warnings（保留环境中不存在本地.venv的提示）、architecture 504 modules/0 violations/0 coverageGaps。完整diff whitespace亦通过。本审查没有再次启动PG或将作者日志说成自己重跑。

证据目录：`/workspace/agent-factory-fix-message-admission-evidence/`。仍未解决/未验证：历史rejected自动迁移、真正终局无task的hold释放均明确不在范围；无真实模型、GPU、Windows、浏览器、整套release/full或部署结论。保留这些限制比扩大本次修复更合适。

## Verification 增量复审 — 2026-10-26

精确增量 `f9fc6ae4fe2a952ce19c2568c4273dcaa0727a0c` → `1ed4c5cf05a82848f791fe2aa9a49a1aa07e2dbc` 只新增34行 `verification.md`；核对完整 `62614177c23c4d2cd0caf6b7c91418e74fde8ad4` → `1ed4c5c` 后，产品与被测源码仍为已审f9fc6ae。

**文档增量 PASS，前述实现结论适用于该最终候选。** 新记录与已读首失败/目标结果一致；额外实读 budget PG 8/8、13.567s、0 skip，以及清理日志 PostgreSQL17.11、fixture数据库/连接为空、base无af_tasks表。配置外.venv提示、未跑Web/audit/full/真实provider等边界均明确保留。没有作者将未验门槛勾成完成，也没有扩大历史rejected/hold修复范围。后续仅原样复制此独立review的文档提交，可用文件字节与源码tree差异核对；不得把复制行为写为新的执行验收。
