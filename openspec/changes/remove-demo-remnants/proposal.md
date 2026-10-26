# Proposal

## Why

移除产品 demo 后，现行指南仍描述默认演示登录/模型，任务页保留不可达 demo 标签，测试专用 Go loopback transport 仍随 core wheel 分发。本次收尾使实际交付与已批准的无 demo 边界一致。

## What Changes

- 修正八份现行指南中的过期默认行为；为 SOURCE_SYNTHESIS_JOURNEY 的旧入口加历史退役标识，保留原验收结果。
- 删除任务页两处 `job.runtime === 'demo'` 展示分支，保留实际来源、证据分类、验证状态和指标。
- 将仅测试引用的 Go loopback transport 及其响应 stream 原样迁入既有测试 helper，同步测试 imports，不留产品转出口；补验证 HTTP peer 未收到 Authorization 的布尔断言。

## Capabilities

### New Capabilities

- `production-authentication`：主规范尚未归档，沿用既有 `remove-product-demo-modes` 的 capability 路径，补充分发、指南与任务展示的具体场景；不新增认证机制。

### Modified Capabilities

无已归档主规范修改。

## Impact

精确基线 `860acd0a3604bc19e4e7f85095f785834a3f23dd`（tree `3b6f8b74bd66417e6d0349a780f7e420321b7920`）。范围限指南、`TaskWorkspace.tsx`、`opencode_go.py` 的两个 fixture 类及其测试消费者。正式 Go Model、通用 transport 注入、身份/权限、历史字段/记录、数据库、CI 门槛均保持；无付费调用、凭据或新部署入口。
