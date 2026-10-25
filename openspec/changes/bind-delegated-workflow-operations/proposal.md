# Proposal

## Why

固定研究Workflow需要把临时原生child作为受控操作等待，并在服务重启或成员撤权后核对/停止原child。当前OperationCustody与DelegationService各自已有可靠身份边界，但没有连接二者的通用适配器；应用自行拼接会重复控制链或把父custody包含在停止判断中而自阻塞。

## What Changes

- 新增core拥有的本地原生delegated-operation runtime，沿既有start/inspect/lookup/cancel协议关联原operation与唯一child request。
- 保留原native wait/requirement与预算祖先关系；lookup只观察，UNKNOWN不重派。
- 为已核验原custody提供撤权后的观察/取消路径，不授予新create权限。
- 复用治理函数已有RunContext与单一OperationCustody.start注入，不扩展ApplicationExecutionContext。

## Capabilities

### New Capabilities

- `delegated-workflow-operations`: 原生Workflow操作与唯一委派child的身份、等待及原custody清理。

### Modified Capabilities

无；当前openspec/specs无已归档能力。

## Impact

基线f25c8992f5c286db3cca3554e3c74a255dfe9f82。涉及core运行时适配器及DelegationService必要的窄原身份清理桥接；当前消费者为固定研究Workflow。需真实PG/native暂停、恢复、重启与撤权验证。没有新队列、恢复worker、凭据、外部模型或UI；基础DelegationService仍拒绝placement，远程后端适配不纳入本变更。
