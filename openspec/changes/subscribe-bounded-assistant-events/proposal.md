# Proposal

## Why

研究应用需要在记录提交后通知少数相关助手，成员离线时仍可在自己的额度内处理经验询问。现有task事件回放与P2消息接口没有事务事件交付、订阅范围和接收者自动预算；不能把反复POST当作可靠恢复。

## What Changes

- 提供与领域记录同一PG事务提交的有限事件outbox，仅保存类型、不透明来源引用与当前授权所需标识，不在core解释研究schema。
- 接收者自行配置明确来源/事件种类的订阅，关联已配置助手端点、有限scope预算、到期与关联深度；发送者不能选择他人资源或扩展订阅。
- 有界交付器只投递同一消息intent、读取原准入收据和结算已有预算；执行、取消与原操作恢复仍由现有native链负责。
- 重复事件/投递去重，离线唤醒遵守接收者权限与预算；未知回执保留，不以超时、缺task或缺native ticket推导重新派发权限。
- 先确定原身份准入/预算原子绑定方案并通过故障实验，随后实现；当前仅设计，不宣称解决P2全部崩溃窗口。

## Capabilities

### New Capabilities

- `bounded-assistant-events`: 应用事务事件、明确订阅范围、有预算的消息交付及原身份观察。

### Modified Capabilities

无主spec；依赖进行中的`member-assistant-messaging`与`scoped-application-content`，不重复其端点与内容读取要求。

## Impact

对应P3与验收A03/A04/A05/A08，实际消费者为`restore-team-research-application`的自动研究记录、定向经验询问与相关通知。涉及core事件服务、消息可信接入口、原准入的预算绑定、生命周期装配与专属PG故障测试。无新模型/provider、消息代理、任务执行器或研究表；C03质量及真实费用仍待外部验收。
