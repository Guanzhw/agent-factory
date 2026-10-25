# Proposal

## Why

基线90f3a131。研究P7离线经验问答需要接收者明确授权的有限模型预算，问题仍只向收发双方可见。现P2直接调用ApplicationRuns.start，无跨消息预算承诺；P3虽有预算，却要求可共享content，不能为复用该入口自动公开问题。

## What Changes

- owner可为新endpoint配置既有scope/caps/deadline，P2发送及可信恢复沿原消息分配与绑定一次预算。
- fresh reservation重查端点、成员、预算和原身份；保留UNKNOWN只读与原操作清理。
- P3已有allocation直接复用，不二次分配。
- 增加接收者只读原task→message输入端口，不增加消息可见范围。

## Capabilities

### New Capabilities

- `bounded-private-messages`: 双方私密消息的接收者预算准入和原输入读取。

### Modified Capabilities

无。

## Impact

AssistantEndpoints/AssistantMessages、P3 prepare窄接点及Store.reserve_task/main装配。复用已有endpoint JSON和budget request映射，不新增表、队列、扫描器、消息协议或ACL/vault。研究QA具体无训练工具Workflow属于应用后续实现；本change不宣称已证明零GPU或真实模型价值。
