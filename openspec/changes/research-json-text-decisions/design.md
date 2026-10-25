# Design

## Context

本地已读取 Agno 3.1.0 `agent/_response.py:get_response_format`：run_context.output_schema 非空且模型无 native structured/json-schema 支持时仍返回 json_object。`platform/agent_factory/byok_model.py:OwnerChatModel._body` 对任意非空 response_format 拒绝。原浏览器失败证据由集成端保留于 `/tmp/af-live-real-browser-body-diagnostic.log`，本变更不复制用户请求/凭据进仓库。

`applications/research/workflow.py` 已有 `decision()` 调用 model_validate_json/model_validate，launch 在 custody 前解析 Decision，record 在持久决定前解析 Evaluation；这些是应保留的实际输入边界。NativeWorkflows 会将每个 Agent model 替换为 WorkflowDecisionModel，复用选定绑定及原身份、预算，不应绕过该包装。

## Goals / Non-Goals

**Goals:** 成员明确选定的文本/工具模型能够进入现有研究决策路径；无效输出仍明确失败且不启动实验。

**Non-Goals:** 不增加 core response_format 支持、provider 特判、parser_model、自动修补重试、模型fallback、第二执行/恢复控制链；不放宽证据或停止语义，不调用真实外部模型。

## Decisions

研究 decide/evaluate 的 Agent 不设置 output_schema；在其原 instructions 后明确要求仅输出一个 JSON object，不带 Markdown/解释，并附相应 `model_json_schema()`。补充 schema 无法表达的当前分支约束：experiment 必需 hypothesis/conditions/goal 且无 outcome；stop 必需 outcome；met 必需原证据；evaluate continue 无 outcome、stop 有 outcome 且均有原证据。wait Agent 不增加 JSON 要求，仍走原工具协议。

launch/record 保留原 Pydantic 解析与领域来源核对。非法 JSON、缺字段、额外字段、无证据达标或无效分支均失败，不抽取代码围栏、不修 JSON、不重问或换模型。这是预先选择的文本协议，不是收到 provider 错误后静默降级。

验证先使用真实 OwnerChatModel 与 httpx.MockTransport，实际构造 ResearchWorkflow 并经过 NativeWorkflows 的 function/model 包装；合成 store/授权及预算 ports 只记录边界调用，不能声称完整 PG/vault 验收。合成 HTTP 返回正确 JSON/非法 JSON/无证据达标与有效评价，断言 wire 无 response_format、原模型 ID 不变、凭据当前检查/授权/预算保留、非法输出零 child/零最终决定。保留已有严格 schema 单测。需要持久原生集成时与 coordinator 串行 PG，复用真实 owner模型路径而非固定 ResearchModel。

## Risks / Trade-offs

文本模型未必遵循 JSON 指令，原严格边界会拒绝；本变更不以放宽解析换取成功率。无真实模型样本就不宣称其输出稳定性或科研自主质量。Workflow 实现 hash 改变，需重新发布引用新 pin 的应用版本；不能改写历史 immutable plan 来冒充兼容。
