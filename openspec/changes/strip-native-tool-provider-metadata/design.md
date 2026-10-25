## Context
真实 factory_wait_operations 是 Agno external_execution 工具。canonical model_protocol._tools 只接受 name/description/parameters/strict；现拒绝有依据，不应放宽。

## Goals / Non-Goals
合法原生工具可到达两种协议；保留 SDK 本地执行标志及暂停恢复。无通用 metadata 框架、重试、模型切换或外部调用。

## Decisions
OwnerChatModel._body 在传给 encode_request 前对 tools 的工具层和 function 层创建浅复制，仅移除 type(value) is bool 的 external_execution。错误类型保留给既有 codec 拒绝；其他未知字段同样保留并拒绝。无需深复制参数，因为此处不改参数。

## Risks / Trade-offs
只适配当前 Agno 已知字段，不预先接受未来 SDK 元数据。用真实工具和 Agent、MockTransport 测两种协议：等待暂停后提供原 requirement 结果继续同 run；原 Function 和传入字典不变。测试是合成 HTTP/便携 native，不是实际 provider 或 PG 验收。
