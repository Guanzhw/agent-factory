# Design

## Context

见 proposal.md。固定 Agno 3.1.0 的 QueueWorker 约束整次 `arun/acontinue`；OwnerChatModel 另外写死 HTTP 10 秒及总请求 30 秒。已复现 31 秒合成响应在 30.032 秒取消。此前真实 Go 失败缺少原始 TimeoutError，不能仅据该复现断言每个旧失败都是同一根因。

## Goals / Non-Goals

**Goals:** 个人模型使用部署已有原生期限，足够慢但仍在有效期限内的响应可用于继续任务。

**Non-Goals:** 不升级 Agno、不新增预算/重试框架，不改变工具 operationSeconds、独立 broker 的 120 秒路径或用户 stop 的协作式语义；不保证提供方停止生成或收费。

## Decisions

1. OwnerChatModel 内部参数 `timeout_seconds` 默认取 `Settings.native_timeout_seconds`；生产 PersonalModels factory 显式传 `context.settings.native_timeout_seconds`。不从用户模型 metadata 再读一份配置，也不把工具期限误作模型期限。
2. 复用 `asyncio.timeout` 的单一请求总期限，HTTP client 的单独 timeout 设为 None。总期限包含 HTTP 连接和响应读取，原有凭据解析/权限核查位置不变；不靠把 30 改成另一常量修复。
3. 不能完全去掉请求期限：摘要经 `to_thread` 和同步 invoke 进入自己的线程，外层原生取消不会立即终止该线程。它仍在本次请求期限内结束；异步请求的原生任务期限更早到达时照常传播 CancelledError。
4. 这是当前 worker 配置给每次请求的时限，**不是剩余任务期限，也不是已持久化的原始 deadline**。现有摘要 claim/attempt 检查拒绝晚回复，UNKNOWN 不重放；无需增加新的持久状态。

## Risks / Trade-offs

- 请求可比以前等更久 → 仍受已有有限请求及原生整体期限约束，验证异步取消和同步等待两条路径。
- 响应未知可能仍在提供方完成 → 保留未知证据，不自动重复调用、不宣称已停止计费。
- 公开仓库测试还有独立 pytest 环境警告 → 先修隔离测试环境，再在相同任务和模型下做新一次验收；不让模型修测试环境制造的假缺陷。

## Migration Plan

无 schema/凭据/数据迁移。按原配置创建模型；回退本片只恢复旧等待行为，不重放已有请求。源码改动、合成因果实验和真实 Go 仓库任务分别记录，准确 head 通过累计独审与完整 CI 才进入适用发布门禁。
