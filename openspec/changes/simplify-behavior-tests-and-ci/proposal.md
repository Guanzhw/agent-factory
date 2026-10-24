# Proposal

## Why

部分测试没有连接到真实观察对象，另一些把序列化细节或内部对象形态当作契约，增加误报与维护成本。完整 CI 还在两个 Linux job 重复执行普通测试，需要以实际行为覆盖和耗时记录决定清理。

## What Changes

- 按 [PR96 计划](../../../docs/plans/test-ci-cleanup.md) 的具体清单删除或改写低价值断言，保留所有权、预算、取消、原操作恢复、依赖方向和资源收尾的行为验证。
- 更新存在审计告警的开发工具，加入锁定 Chromium 的短流程，并让 Linux 全量行为由 PostgreSQL job 统一执行；Windows 兼容性和本地完整入口保留。
- 对基线与最终提交记录实际用例、跳过、阶段耗时和 job 用时，经独立审查后合入。
- 修复完整基线实际暴露的 Windows 夹具错误：隔离安装保留 pywin32 的必要启动路径，并为并发 MCP 回调提供独立数据库连接。

## Capabilities

### New Capabilities

无。本次为测试、开发工具与 CI 调整，`skip_specs: true`；产品行为契约保持不变。

### Modified Capabilities

无。

## Impact

涉及选定 Python/Web 测试、前端依赖边界检查器、开发依赖、浏览器 smoke、CI 与开发文档。实施基线为 PR96 的 `3e206920b8ea86598fca35d3cedcd80dfbdf160d`，其父提交是已合入 PR95 的 `246f06541b21915392a77555e24f3f617d34de9f`。
