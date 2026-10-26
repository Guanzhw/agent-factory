# Proposal

## Why

基线 `62614177c23c4d2cd0caf6b7c91418e74fde8ad4` 的 C2 将暂时任务容量 429 误记为永久拒绝，原消息和预算无法随容量恢复继续准入；C3 在无 automaticBudget 时跳过最终发送者、端点及原请求复核。

## What Changes

- 为真实活跃任务容量不足返回稳定错误码，使既有事件扫描保留 pending 和同一 message/request/allocation。
- 将新消息共同的 owner、sender、endpoint enabled 与完整 prepared-request 指纹校验移到预算条件之外。
- 补失败回归及 PostgreSQL 真实准入验证，保留 reserved/UNKNOWN 原任务只观察和现有终局拒绝栅栏。

## Capabilities

### New Capabilities

- `assistant-message-admission`: 明确所有新消息的共同准入边界及暂时容量不足时的原身份恢复；已有主 specs 尚为空，延续现有 messaging/events change 的职责。

### Modified Capabilities

无。

## Impact

仅涉及 Store 容量错误、AssistantEvents 失败分类、AssistantMessages fresh 校验和对应测试。无新控制器、daemon、策略框架、依赖、访问权限或容量放大；无预算端点无需新增配置。真正终局且无 task 的 allocation 释放不在本修复范围，继续保留既有 hold。
