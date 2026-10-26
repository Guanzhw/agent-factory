# Tasks

## 1. 方案与说明

- [ ] 1.1 非作者审查本方案与基线反例，记录精确 base/head 和简洁性结论后实施。
- [ ] 1.2 修正 design 指定的八份现行指南并为 SOURCE_SYNTHESIS_JOURNEY 加退役提示；逐条对照配置/API，确认历史 audit/spec/review/evidence 不变。

## 2. 产品与测试边界

- [ ] 2.1 迁移两个 loopback fixture 类及所有测试 imports，保留 wire/cleanup；运行 `test_opencode_go`、`test_go_development_profile`、`test_go_http`，补实际 loopback 双协议无 Authorization 布尔断言并检查正常/异常关闭。
- [ ] 2.2 删除 UI 两处不可达 demo 分支，保留 source/证据/验证字段；运行既有 task-history 测试及 `npm run check`、生产与全量 npm audit。
- [ ] 2.3 执行 Python ruff/pyright/architecture 和独立 wheel 内容、隔离 import 两个既有测试；核对 wheel 无 fixture 类、无 tests 依赖、正式 Go adapter 可导入，不声称 PG 生命周期验收。

## 3. 最终验收

- [ ] 3.1 记录目标检查及首失败/未验事实，通过 OpenSpec strict；非作者复审精确完整 diff 与简洁性，完成整改复审，再由协调者核验发布后精确 head 的适用 CI。
