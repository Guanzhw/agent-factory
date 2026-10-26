# Independent specification review

Reviewer: `cleanup_review`（非方案或实施作者）；证据字节核对由独立只读 `evidence_check` 协助。

精确范围：`62614177c23c4d2cd0caf6b7c91418e74fde8ad4` → `ed067f7926f35484be31810426c41d1be05c0429`。已审全部四个方案文件，并对照实际 worker、fixture、报告生成器及现有验收记录。

**方案 PASS；允许按此方案实施，不等于实现或运行验收通过。**

- 两份 MCP JSON 与固定历史 `a02438e17316f4b748b2ed6624fe920bc449050f` 逐字节一致，共 10,921 行；现有文字保留原身份、UNKNOWN、未 dispatch、stopped=false、transport closed、回调完成与未闭环结论。固定历史链接足以保全完整轨迹，不需再加报告平台或重复摘要。
- 浏览器 aggregate 仅有 ok 和重复的两个 results，分别等于 desktop/mobile 子报告；未发现读取 results 的消费者。同步当前产物与唯一生成器为相对路径索引属于批准去重范围。实现须覆盖 desktop/mobile/both 选择，保持子报告及截图字节不变；原文链接可注明“报告索引”。
- storage 当前默认诊断 worker 和 teardown 复制确有额外开销。测试专用显式开关复用原普通/诊断 worker，不需新框架；两模式仍须各执行原测试一次，原业务断言和期限不得修改，保留首次失败及实际清理结果。
- create_fixture_app 的材料初始化确实由下一层重复执行；member_headers 的 auth 参数确实未使用。删除冗余调用/参数并保留 initialize_members、外部测试 issuer 和现有授权断言合理。

未发现过度设计、防御层或无谓报告扩张；四文件 76 行的工具维护方案可接受。产品代码、依赖、CI、remote ACK/removal 修复、demo 删除及历史对象均不在修改范围。

本次为只读方案审查；`git diff --check` 通过，未运行产品/PG/浏览器验收。完成实现后须复审精确完整 base/head diff、目标检查和两模式真实 storage 回执；发布仍为独立 Draft PR。

# Independent implementation review

Reviewer: `cleanup_review`（非实施作者）；`evidence_check` 独立只读核对证据。

精确完整 diff：`62614177c23c4d2cd0caf6b7c91418e74fde8ad4` → `1eb12f16c998777d4fb7eaf5702af611242773d1`，17 文件，+136/-11941。方案先行 `ed067f7926f35484be31810426c41d1be05c0429` 已独立 PASS。

**代码与简洁性 review PASS，无待整改阻断。**

- 全部变化均为已审方案、验收证据、测试夹具及报告生成器；生产源码、依赖、CI、Web 与 PR138 不在 diff 中。remote ACK/removal 修复及原业务断言未改，无 demo 恢复。
- 两份 MCP JSON 与固定 `a02438e17316f4b748b2ed6624fe920bc449050f` 历史字节一致；两条固定链接正确，无残留失效相对引用。原失败身份、UNKNOWN、未 dispatch、stopped=false、transport closed、回调完成和未闭环结论保留。
- 浏览器索引只保存相对子报告路径；两个子报告和十张截图与基线逐字节一致。生成器保留原 desktop/mobile/both 循环及每个结果写入，未改变验收执行或宣称新浏览器证据。
- storage 仅在显式环境变量为 1 时选诊断 worker 和复制文件；默认仍调用原 worker/清理。AST 比较确认业务 test 方法与基线完全相同，全部断言及期限保留；现有 finally 保证证据复制失败也进入原清理。
- 材料初始化仍由 publish_fixture_applications 完成一次；member_headers 所有调用点已同步单参数，initialize_members、外部 issuer、禁用成员及 owner 可见性断言保持。

实读本候选相关日志：默认 storage 1/1（7.578s）、diagnostic storage 1/1（6.707s），零跳过；前者无诊断文件/留存目录，后者保留原诊断；两者均确认原 child 退出、工作目录和隔离数据库删除，HTTP read timeout 仍为 15。fixture lifecycle/identity/publication 共 34/34（22.269s）通过。未另跑重型 PG；完整 diff whitespace 检查通过。

这是源码/已记录目标检查结论，不替代发布后精确 head CI。后续 verification/task 文档增量仍需复审；该独立 PR 保持 Draft 直到适用检查终态成功。

# Independent Q2 specification review — 2026-10-26

Reviewer: `audit_quality`，非本次方案/实施作者。精确方案范围：`fdb78b5793b74b34334305a1f5b1c9ee4340d469` → `4ac2bb06d20aa0cb5aeb16b99a3f1c261bf6e3eb`，3 文件 +11 行。

**Q2 方案 PASS，允许按此窄范围实施；不是实现或端到端运行 PASS。**

- 实读当前 `accept_research_assistant_ui.main` 与完整方案 diff：同一 result 被写入子报告和 aggregate，复用已有 `reports` 相对路径即可去重；未发现依赖该新生成 aggregate `results` 的代码消费者。
- 只改报告写入，保持 `run`、三种 viewport、子报告/失败截图/日志及历史产物；不引入报告框架、兼容重复字段或额外规范。
- 用 actual main AST 与合成依赖验证三种索引、子报告完整和异常关闭，是与此次变化相称的验证；保留旧 head 反例，不将其声称为真实 PG/浏览器验收。
- 后续需审精确实现完整 diff 与实际检查回执；旧 PR139 PASS、历史验收和本次方案 PASS 均不替代该复审。无需为此重跑旧 storage/PG 验收。
