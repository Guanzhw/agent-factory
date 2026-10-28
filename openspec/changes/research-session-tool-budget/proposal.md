# Proposal

## Why

真实 DeepSeek 代码任务在首修复轮的第 8 次工具之后无法执行编辑，成员被迫显式续轮；修复后最终 diff 复核也被同一上限挡住。现有部署设置和原生 Agent 已支持可配置次数，正常启动与新会话默认尚未接通。

## What Changes

- 将现有 `Settings.max_tool_calls` 接到 `FACTORY_MAX_TOOL_CALLS`，沿用 1–128 的预算范围，未配置仍为 8。
- 新 Research 会话采用部署工具默认，已有会话/Plan 的显式额度不回写；正常编码部署先以 32 作为待实测候选。
- 用一个完整用户目标验证复现、改码、目标/full 测试、核 diff 与结束，不在 QA 中人为要求观察后先停。
- 保留现有持久预算、取消和 UNKNOWN；明确部署上限提高后，旧低预算可能由 durable guard 结束而非 native 工具额度回复，不宣称旧收尾形式不变。

## Capabilities

### New Capabilities

- `research-session-tool-budget`: 正常部署配置与新研究会话工具额度接线，以及完整代码任务和既有显式额度的行为验收。

### Modified Capabilities

无已归档 capability；延续 `personal-research-sessions` 与 `research-coding-task-workspace` 已有契约。

## Impact

基线 `05233580b04f290c40d463a7240d05cb213f45ac`，独立分支 `feat/research-tool-budget-20261028`。产品范围仅 `platform/agent_factory/config.py`、`applications/research/session_setup.py` 及相应测试/启动说明。保留 Agno 3.1.0；不改模型分派、运行循环、数据 schema、网络或当前冻结 coding 候选，不新增预算框架、付费 fallback 或 demo。
