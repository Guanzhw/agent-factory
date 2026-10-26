# R1 验证记录

- 基线：`62614177c23c4d2cd0caf6b7c91418e74fde8ad4`；方案 `673313df24f3e9b37e9fae34f093c113c213863c` 已由非作者审查 PASS。实施作者不自审，不勾任务。
- 首次便携回归：`/tmp/research-r1-first-failure.log`，6 项、10 errors；合法中文终稿在旧 content 16 KiB 校验处 422，新字段亦不存在。保存原始错误，没有改输入或截断。
- 最终便携选择：`test_application_content_artifacts test_research_publication test_application_content test_research_rounds test_research_qa test_research_associations test_research_content_consumers`，42 项 PASS，4.985 秒；`/tmp/research-r1-portable-final.log`。真实 SQLite content/artifact/event/transaction，native/scopes 为 fixture，不能代替 PostgreSQL 结算证明。
- 用例覆盖：旧 inline 指纹、双字段/缺正文拒绝、安全数据/JSON 结构/owner、20 证据加长正文、分页、源撤回先于解封、制品损坏/缺失、两处写后回滚与重试唯一、真正单体超预算仍保留原负结论。QA、关联、peer input、前轮 context 收到完整中文对象；超过原 QA 16 KiB 上下文时仍按原规则不进入模型。
- 真实 PostgreSQL 17.11（coordinator 独占时隙）：同一新增 artifact 回归先用冻结基线产品路径运行，18.107 秒失败，`/tmp/research-r1-pg-baseline.log`。`3cf840aa` 首跑两项中一项 PASS；旧 pin fixture 只改 plan 未同步 allocation 摘要，原结算完整性校验阻断，`/tmp/research-r1-pg-first.log`。未放松生产校验。
- `ddbb2e3c0ad1c6e3f0f2d90f6cfb32db7ebf645c` 将历史 fixture 的 plan/hash、allocation plan_sha/binding_hash 在同事务构造一致。两项 `ResearchPublicationPostgresTests` 8.128 秒 PASS，`/tmp/research-r1-pg-fixed.log`：真实 native 任务已停止；artifact/publication 写后故障回滚 terminal、SETTLED、事件和正文；observer 重试后单一 task/artifact/publication 与 SETTLED。HTTP `/application-content/{id}` 完整返回原中文 goal/decision。
- 旧 pin 证据边界：真实 native 执行停止后 seed 精确基线身份与一致原 allocation，验证仅完成 hooks 接管。原 pin 执行检查 409、无 observe/reconcile、未知 revision 不被接管。没有声称真实旧 paused 工作流可继续执行，也没有用新代码执行旧定义。两次 PG fixture 均清理数据库/worker；driver 查询仅剩系统数据库。
- 静态：Ruff 全目录 PASS；Pyright 使用 `/tmp/research-r1-pyright.json` 的当前源码 extraPaths 和现有 venv，0 errors/warnings；Python ownership 509 modules、web ownership 101 modules，零 violations/gaps；`git diff --check` 和严格 OpenSpec validate PASS。初次 Pyright 未定位 venv，第二次跟随 cleanup editable 指向旧代码；显式配置当前源码后复核。另一次临时配置 absolute include 不被 Pyright 接受，已改 relative include，未隐藏错误。
- 前端：`NODE_OPTIONS=--no-experimental-webstorage npm run check` PASS，53 files / 490 tests，lint/typecheck/build 全过；`/tmp/research-r1-npm-check.log`。首次 npm 默认缓存目录不可写，改为 `/workspace/.npm-cache` 后安装成功。官方 registry 的生产及完整 dependency audit 均 0 vulnerabilities，日志 `/tmp/research-r1-audit-{prod,full}.log`。
- 未验证：真实模型、GPU、生产 IdP、新浏览器 E2E；UI source 复用已有 generic content 渲染，HTTP 完整对象已实测，发布失败只新增明确状态文案。R2 多轮交付 aggregate 500 与 R3 ending 待独立变更，不记本次已修。

最终源码全量复审与接纳由非作者 reviewer / coordinator 记录；上述工具日志保留原尝试，历史 PASS 不替代本轮判断。
