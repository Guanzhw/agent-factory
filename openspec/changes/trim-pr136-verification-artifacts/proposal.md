# Proposal

## Why

PR #136 的生产代码净减少，但两份 MCP 原始诊断占 10,921 行，浏览器总报告逐项重复 desktop/mobile，临时 storage 诊断还进入了默认测试。独立清理这些维护负担，保留失败事实和原始历史可追溯性。

## What Changes

- 删除当前树中的两份 MCP 原始轨迹，以简短失败事实及固定提交链接保留证据；浏览器总报告和生成器改为子报告索引。
- storage 测试默认使用原 worker；仅显式开启诊断时加载诊断 worker、复制诊断文件。
- 删除 fixture 的一次重复材料初始化和 `member_headers` 未使用的 `auth` 参数，同步所有调用方。
- 审计 Q2 后续：将 `accept_research_assistant_ui.py` 的新总报告也改为相对子报告索引；不重写其历史验收产物。

## Capabilities

### New Capabilities

无。仅维护验收记录与测试夹具，使用 `skip_specs: true`，不新增产品行为规范。

### Modified Capabilities

无。保留原断言、超时、UNKNOWN/remote ACK、removal 修复和正式认证边界。

## Impact

基线 `62614177c23c4d2cd0caf6b7c91418e74fde8ad4`；历史比较为 PR #136 `9454000e088ca6fba55621b8b2443ab55ffcc764` → `a02438e17316f4b748b2ed6624fe920bc449050f`。只改该 PR 的证据、相关验收脚本和测试夹具；不修改生产代码、CI 门槛、Git 历史、截图或用户数据，不恢复 demo。与 Windows PR #138 分支和审查分离。

Q2 增量基线为已发布 PR139 `fdb78b5793b74b34334305a1f5b1c9ee4340d469`。此次明确扩大一个同类报告生成器的范围，复用已有 `reports` 形状；其余已验证清理不重做，原审计不改写为通过。
