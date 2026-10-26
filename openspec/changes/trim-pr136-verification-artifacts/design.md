# Design

## Context

动机和精确基线见 [proposal.md](proposal.md)。现有总报告两个 `results` 分别与 desktop/mobile 的 `evidence.json` 完全相等；`StorageProcessTests` 固定选择诊断 worker 并在每次 teardown 复制文件。`create_fixture_app` 与被它调用的 `publish_fixture_applications` 都初始化材料；`member_headers` 不使用 `auth`。

## Goals / Non-Goals

**Goals:** 当前树保留一份有效证据；默认测试不运行临时诊断；保持原测试的输入、执行身份、断言和截止时间。

**Non-Goals:** 不引入证据框架、通用诊断开关体系或产品 API 变化；不顺带重写其他历史报告和 MCP instrumentation；不把模型/GPU/生产 IdP 未验项改成通过。

## Decisions

1. 删除 `remove-product-demo-modes/evidence/mcp-schema-{original-failure,instrumented-single-run}.json`，更新既有 `verification-testing.md` 的两处链接为 PR136 head 的固定 GitHub blob URL。保留原 task/run/request 身份、UNKNOWN、未 dispatch、`stopped=false`、transport closed、回调完成和历史失败未闭环事实；轨迹和成功对照仍由原提交完整保存，不再新增汇总 JSON。
2. 将 `research-browser/evidence.json` 的 `results` 改为 `reports` 相对路径列表，保持 `ok` 和两份子报告、截图不变；`scripts/accept_research_evidence_ui.py` 以后也写相同索引。该文件是人工验收产物，不是产品接口；不为旧格式再留重复字段。
3. 仅当 `FACTORY_STORAGE_DIAGNOSTIC=1` 时由 storage fixture 选择 `controlled_storage_diagnostic_worker` 并保存诊断；未设置时使用 `controlled_command_worker` 与原清理。worker 的 149 行保留作按需入口，不复制到新框架。记录一条可运行诊断命令；不延长原 15 秒 HTTP 截止时间。
4. 删除 `create_fixture_app` 中被下一层覆盖的 `publish_fixture_materials` 调用；`member_headers(owner)` 保留现有外部测试 issuer 签发逻辑并更新全部调用点。成员初始化仍归原 `initialize_members`，不变更认证/授权断言。

## Risks / Trade-offs

- 历史轨迹离线不在当前 checkout → 固定到 `a02438e17316f4b748b2ed6624fe920bc449050f`，核验被删内容与该 Git 对象一致、关键失败事实仍在文字记录。
- 默认与诊断路径可能分叉 → 两种模式各运行原 storage 测试一次，核对同一测试 ID/断言、默认无诊断文件、开启后有诊断文件且清理结束；不反复重跑以覆盖失败。
- 辅助函数签名影响少量调用者 → 搜索全部调用点，运行既有 fixture lifecycle、department publication 和相关 Python 静态检查；浏览器生成器改动只影响报告结构，做保存产物结构/链接核对，不冒充新浏览器运行证据。

## Migration Plan

先提交本方案并由作者之外审查；再实施、运行相关检查并交最终完整 diff 简洁性复审。无数据库迁移；如有问题可正常 revert 该独立提交。发布到独立 Draft PR，保留精确 base/head 与复审结论，不与 PR138 混合。
