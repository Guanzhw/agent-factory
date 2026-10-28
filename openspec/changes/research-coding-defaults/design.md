# Design

## Context

沿用 `research-session-tool-budget` 和 `research-model-request-lifetime` 的配置契约。真实模型第4次公开仓库 campaign 保留FAIL：child执行ls违反额外提示；源代码修复和206测试由独立复跑证明。该失败不通过本片修改提示或重跑抹去。

## Goals / Non-Goals

**Goals:** 普通新会话实际获得已验证的小任务起始配置，显式较低配置仍生效，旧持久额度不被覆盖。

**Non-Goals:** 不改 Budget/LegacyBudget、模型输出缺省4096、现有模型配置版本绑定、并发worker、工具隔离、审批或费用模型；不声称默认输出额度已足够所有模型。全站界面易用性与真实部署仍在后续。

## Decisions

1. 只调整 `Settings` 三字段及 `from_env` 对应缺省；不创建 profile 或另一层策略。已有范围校验不变。
2. Research options/setup、原生 Agent、QueueConfig 和 OwnerChatModel 继续消费现有 settings。使用现有个人模型配置时可保留16384输出额度，明确这不是模型空配置验收。
3. 旧 Plan 的8次工具/8秒操作不回写；旧低工具额度仍由持久 pre-hook 拒绝越限副作用。共享原生 Agent 可尝试更多调用，当前 worker 的原生时限变长，因此收尾方式可能变化，不能宣称所有旧运行零行为变化。
4. 验证沿真实路径：无这三个环境覆盖的新会话准备及原生构造；显式旧值覆盖；原持久低预算拒绝；实际超过8秒的短测试命令和超过8次的脚本原生调用。不用再次随机重跑公开任务只求绿色；已有真实Go任务证明32/120/300能完成该样本，本片证明普通配置确实到达同一执行边界。作者外复审可用已有Go做一次聚焦审查，结论必须经人工核对。

## Risks / Trade-offs

默认单轮可工作更久、调用更多，但不是模型费用预算；用户停止和既有权属校验保留。旧环境显式配置仍可限制任务。没有新增后台调用、自动升级额度或收费fallback。

## Migration Plan

无需迁移。更新部署代码后，未显式配置的 worker 使用新默认；既有 Plan 不重写、不重放。准确head经独审及full CI后才进入适用发布门禁，既有拒绝不因本片解除。
