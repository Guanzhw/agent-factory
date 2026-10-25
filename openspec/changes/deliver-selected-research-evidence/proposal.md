# Proposal

## Why

研究当前终态共享运行事实与agent决定，尚没有原CLI测量、源码/配方与可继续成果的完整来源链。P6/P8需要自动精选真实输出并生成可复现交付，不能把模型补写的事实或全量私有日志当团队证据。

## What Changes

- 一个明确的CLI证据消费者：原native child继续使用MemberCliAdapter；parent结果步骤按owner预先确认的材料pin及输出字段选择收集原完成回执，用原application_context写精选artifact。
- 复用ApplicationContent分享有限证据与不可变成果manifest，保留负结果和缺项；当前actor有界下载选定字节，不执行配方、不清理源。
- 明确所需core原工具结果只读口，独立审查后由coordinator集成，不在应用直查effect表或复制执行链。

## Capabilities

### New Capabilities
- selected-research-delivery: 受选择约束的原CLI证据、自动分享与可复现成果导出。

### Modified Capabilities
无。

## Impact

基线1b58d79。应用evidence/delivery服务、projects确认契约、rounds/workflow结果与完成接缝、public显式装配及专属测试；不改QA、模型内核、UI或默认core装配。core只读接点为待review依赖，不在应用补私有旁路。无新runner、队列、vault、ACL、归档或恢复链。真实GPU/科研模型验收仍独立。
