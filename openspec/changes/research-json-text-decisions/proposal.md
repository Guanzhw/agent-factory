# Proposal

## Why

真实浏览器选择成员模型后，研究决策步骤在首次模型请求前失败。Agno 3.1.0 对设置了 output_schema 的模型请求 response_format，而现有 OwnerChatModel 明确只支持文本/工具，不支持该格式参数；先前固定模型 fixture 未覆盖这条真实适配器边界。

## What Changes

- 研究 decide/evaluate 明确使用 JSON 文本协议：指令包含现有 Pydantic schema，模型响应仍为文本。
- 原 launch/record 边界保留严格 Decision/Evaluation 校验，不增加解析模型、修补重试或替换用户模型。
- 使用真实 OwnerChatModel、合成 HTTP 与原生 Workflow 包装验证合法/非法响应、原授权与预算调用。

## Capabilities

### New Capabilities

- `research-json-decisions`: 研究应用通过明确文本协议取得结构化决策，并在执行边界验证。

### Modified Capabilities

无。现有研究规范尚未归档到主 specs；本变更细化既有严格决策要求，不修改核心模型支持范围。

## Impact

仅 applications/research/workflow.py、专属应用测试与本规范。现有绑定、凭据、预算、原生队列/恢复和 core 不改。基线30699a3；不调用外部真实模型，不将合成 HTTP 结果作为真实科研验收。
