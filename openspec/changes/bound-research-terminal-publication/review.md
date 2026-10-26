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

## R1 完整实现复审 — PASS

- 精确累计范围：`62614177c23c4d2cd0caf6b7c91418e74fde8ad4` → `d9f92acffcfd6937c4c43ad8c3ddc205e6e1b9f6`，19 文件。已逐项复审 6 个产品文件、5 个测试/fixture、API 文档和该 change 的规范/验证记录；未继承方案 PASS 为实现结论。R2 后续方案目录不属于本 R1 实现范围。
- 正文引用复用原 Store 制品与 content 授权，先 `_readable` 后读取正文，不增加旁路缓存；owner/task/hash、原结构与安全数据检查、raw 与 UTF-8 序列化单体限额均保留。旧 inline 请求去除新增空字段，原 fingerprint 和幂等重读不变。正文独立于 20 精选附件，消费者继续拿到相同 `content` 对象，无分散解封层。
- finalizer 在原事务内写正文、事件、publication 与领域终态；仅确定尺寸超出既有配置时明确 publication_failed，保留原决定和 outcome、不触发后继。其他权限、制品、写库错误仍回滚。预算失败文案不声称科学失败或完整成果已发布；QA/关联仍保留原模型上下文预算。
- 旧 pin 只匹配已部署 `62614177` 的精确 hash，只有 completion callback，无旧执行器或 observe/reconcile 复用。独立审查先发现历史 PG fixture 仅替换 plan 会破坏 allocation 摘要一致性；作者在 `ddbb2e3c` 只修测试，原生产完整性校验未变。验证仍如实限定为当前 native 停止后 seed 一致历史身份，不声称真实旧 paused 工作流续跑。
- 独立运行上述 R1 head 的 `test_application_content_artifacts test_research_publication test_research_content_consumers -v`：**10 tests / 0 skip / PASS**。覆盖授权先于解封、损坏/缺失、旧指纹、完整中文、真实 SQLite 写后回滚重试及现有消费者。累计 `git diff --check` 通过。
- 另保存最小组合复现 `/workspace/cross-pr-audit/r1-selected20-check.py` 及同名 `.json`，在 R1 产品源码无变的后续纯 R2 方案 head `af84528297d9ec03f8dd181dfaeae60319199c8d` 运行：真实 Research finalizer 两次、20 个原证据 + 独立长中文正文，peer 完整等值，21 个制品总数且无重复正文，terminal published。native/custody 为 mock，SQLite 不是 PG。命令：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=platform:platform/tests:deployment:applications:applications/tests /workspace/agent-factory-cleanup/.venv/bin/python /workspace/cross-pr-audit/r1-selected20-check.py`。
- 已核对作者 portable 首败与最终 42 PASS、PG 基线原 422 失败、历史 fixture 首败和修后两项 8.128 秒 PASS 的日志及断言。真实 PG terminal/settlement/artifact/event/publication 回滚与重试、HTTP 完整对象证据属于 `ddbb2e3c`；到本次 head 的产品增量只有已入场 execution 非空断言，reviewer 未重跑 PG。静态/前端验证按 verification.md 的实际边界记录，没有浏览器或真实模型声明。
- 结论：本 R1 完整范围 **PASS**，未发现剩余阻断项。R2 聚合与 R3 ending 尚待独立方案/实现，R4 由另一个 reviewer 负责；本结论不解除 coordinator 的组合验收与整批 Draft/merge hold，也不批准部署中间 pin。
