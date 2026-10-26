# Verification

基线 `860acd0a3604bc19e4e7f85095f785834a3f23dd`；先审方案 `73464901411b244634a83856feb0d35fe44967ef`、被测实现 `f2b4d39de97df4b87a3b0d27c5c52936eddc4512` 均已由 `audit_quality` 独立 PASS。后续仅更新审查/任务文档；发布后精确 head CI 另由协调者核验。

| 检查 | 首次结果 | 边界 |
| --- | --- | --- |
| Go contract/profile/HTTP 与两项独立 wheel selectors | 52/52 PASS，0 skip，3.899s | 三模块及 wheel 内容/隔离 import；不含 PG 生命周期 |
| 新增 loopback 用例 | PASS | 两协议各正常/消费中断，共 4 次本机 socket 请求；peer 只记录 Authorization 是否存在，全部 false；底层 transport 每次关闭一次 |
| `npm run check` | PASS；53 文件、497 测试 | lint、类型、含 task-history 的全部前端单测、正式 build；保留已有大 chunk 提示 |
| npm audit 生产与全量 | 均 0 vulnerabilities | 显式官方 registry，moderate 门槛 |
| ruff / pyright / Python architecture | PASS；0 errors / 14 warnings；528 modules，0 violation/gap | 14 条 warning 均为 Linux 上既有 Windows pywin32 源码不可解析，未抑制 |
| class/剩余产品 AST 与实际 core wheel | PASS | 两迁移类及剩余产品 AST 与基线相同；wheel 无 fixture 类/tests，真实 Go Model 保留，打包源码字节一致 |
| OpenSpec strict / diff check | PASS | 现行说明与历史标识分开，历史 synthesis 正文未改 |

首次环境检查发现主 checkout 的 Node 依赖与锁文件不一致（vite/vitest 旧版、happy-dom 缺失），因此在本分支执行锁定 `npm ci`、`uv sync --frozen`；未改 lock。所有上述行为检查首次通过，无失败重跑。便携 Python 选择为 `test_opencode_go`、`test_go_development_profile`、`test_go_http` 及 `CorePackageDistributionTests.test_wheel_contains_only_core_sources_and_no_application_dependency`、`test_all_installed_core_modules_import_with_application_packages_absent`。

本机日志和独立 wheel 在 `/workspace/demo-remnants-evidence/`，不入 Git。没有运行无关全套 PG、实际外部 Go/模型、GPU、生产 IdP 或部署验收；合成 transport 结果不提升这些未验边界。完整 diff 简洁性复审已通过；任务 3.1 保留发布前状态，发布后 fast 及 main CI 的最终验收以 PR 的精确 head 回执为准。

## Current-documentation follow-up

上文为 PR #148 发布前记录；协调者已核验合并及 [main CI 40295987780](https://github.com/Guanzhw/agent-factory/actions/runs/40295987780)，任务 3.1 已关闭。本次基线 `f3f931b06f11b7ea910a9efe3d5b8a8ba89442ff`、统一方案 `51f124d7a0fd81d0ab3bb694b6c709258a5a4303` 已获非作者方案 PASS。

12 份指南逐条对照默认/显式装配、个人适配器注册、配置/plan policy 与现存测试入口；7 份历史文档的原验收正文保持，新增相对链接目标均存在。OpenSpec strict、完整 diff/空白及仅 Markdown 范围检查首次通过；产品、测试、CI 无变更，不重复运行产品测试或服务。任务 4.1 等待精确候选独立完整复审与发布后 CI；OpenSpec 路径按现有规则走 fast，由协调者核验最终回执。
