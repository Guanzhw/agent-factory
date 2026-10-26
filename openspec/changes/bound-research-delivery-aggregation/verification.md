# R2/R3 验证记录

- 基线：已审 R1 `e4afcb6eb230ad079f13ac87dc5e3d581701b390`。原方案 `951e0e1f` 移到新工作树后为等价 `103ec594`，由独立 reviewer 确认；未改写原历史。完整方案及 `round_not_published`、目录兼容两个小增量均先获独立 PASS 再实现。
- 原首败：原树 `951e0e1f` + 新回归，7 项中 3 failures / 3 errors，`/tmp/research-r23-first-failure.log`；合法双长记录/中文制品正文卡旧 16 KiB aggregate、ZIP 超限未拒绝、ending 未保留/依赖缺失。UI 新增 ending 断言失败，`/tmp/research-r23-ui-first-failure.log`。两测试逐字节复制到新树后继续，未伪称新树重跑首败。
- 复审发现旧目录兼容回归：旧合同允许的 2016 字节正文在同 1024 字节配置下已可创建/列目录，新累计预算使 list 413。独立旧源码→新同 DB 对照脚本见 `/workspace/cross-pr-audit/r23-list-boundary-check.py` 及 before/after JSON；作者首败 `/tmp/research-r23-list-first-failure.log`。`2f0cb98138b1a9dceb6429b81a8b1c07a5ba3f00` 修为 list 只保留逐项当前授权、不收集正文/累计包预算；read/download 仍 413，撤回仍隐藏，无 catch 413 旁路。
- 最终定向便携：`test_research_delivery_contract test_research_delivery`，19 项 PASS、2.613 秒，`/tmp/research-r23-portable-final.log`。新 10 项覆盖两条合法长记录完整等值/无影子副本、旧格式、R1 中文正文加 20 精选证据只导出一次、真实 ZIP 等号/减一字节/HTTP 413/无失败回执、selected artifact 损坏/缺失、手动与自动 ending 原文和分类、无/旧快照不补造、未发布轮依赖与同 owner team→personal、peer-only 当前 owner 停用、普通 selected personal 正向、组包期间撤回、未发布终态缺证。SQLite 为真实存储，scope/native fixture 不是生产执行证明。
- 真实 PostgreSQL 17.11、coordinator 独占时隙：`2f0cb98` 跑 `ResearchDeliveryPostgresTests` 的 `test_real_cli_selected_evidence_and_other_member_reproduction`、`test_peer_source_follows_actual_cli_artifact_and_revocation_denies_author`、`test_manifest_source_withdrawal_is_serial_with_authorized_snapshots`，24.111 秒，前两项 PASS、第三项 ERROR，原始 `/tmp/research-r23-pg.log` 保留。
- 第三项旧 fixture 直接插入只有 sourceIds/伪 records 的 body，缺所有真实 create 都有的 recordIds，故新解封 KeyError。`db49d9c0b8c075ecbb8d5425f37505b5cb1e1e09` **仅改测试**为真实 native stop→真实 create，全文与原 source.content 等值；保留双向 thread barrier、等待期限和撤回拒绝。独立 reviewer 核准该增量，不给产品增加缺字段 fallback。只重跑受影响一项 3.673 秒 PASS，`/tmp/research-r23-pg-withdrawal-fixed.log`。不能把三项首跑写成全过。
- 真实 PG 证明当前选中 CLI 原证据及另一成员独立复现、原 peer source 撤回拒绝导出/读取、授权快照与撤回的双向锁序；只用可控模型和本地 Python CLI。清理后仅系统数据库，fixture sessions=0，相关 fixture process=[]，PG slot 已归还。
- 最终前端：`NODE_OPTIONS=--no-experimental-webstorage npm run check` 全 PASS，53 files / 492 tests，含 ending 原文、原 Agent 分析标签与撤回隐藏的 8 项详情用例；`/tmp/research-r23-npm-check-final.log`。两类官方 registry audit 均 0 vulnerabilities，`/tmp/research-r23-audit-{prod,full}.log`。未改依赖。
- 最终静态：全目录 Ruff PASS；`/tmp/research-r23-pyright.json` 指向本树源码与现有 cleanup venv，Pyright 0 errors / 0 warnings，`/tmp/research-r23-pyright-final.log`；Python ownership 510 modules / web ownership 101 modules，零 violations/gaps；diffcheck 与严格 OpenSpec validate PASS。
- 产品范围仅 delivery.py、交付 UI/type；没有修改 Research workflow pin、核心执行、来源权限或资源创建路径。规范/验证/测试不混 R4 新准入。新 manifest 固定原 references/ending，读取使用相同完整包预算，目录只核权限，不新增任务状态机、缓存或后台导出器。
- 未验证：本 PR 未跑新的真实浏览器 E2E、真实付费模型/GPU/生产 IdP；DOM 与真实 HTTP/native/PG 证据分别如上。原 ending 的 actor 未存则不猜测，resourceCleanup=not_observed 不提升为停止证明，原负结果不裁剪。

实施作者未自行勾选任务或宣布独立审查 PASS。最终完整 `base..head` 复审由非作者记录，coordinator 核对最终源码/回执后维护任务和发布。
