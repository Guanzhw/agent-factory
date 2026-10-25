# Proposal

## Why

现有P2只有问句及执行收据，接收者无法沿原消息回复；反向send会再次启动任务。当前应用经验问答需要双方私密且随来源撤回隐藏的回答，不能复制一套应用ACL。

## What Changes

- 原消息增加一次可信原task回复，返回双方受限投影，不创建执行。
- 来源仅引用现有不可变ApplicationContent ID，提交与读取按双方当前读权并与撤回串行。
- nullable JSON兼容迁移，保留原问句/收据/历史数据。

## Capabilities

### New Capabilities
- private-assistant-replies: 原消息受限回复、来源撤回和无执行读取。

### Modified Capabilities
无。

## Impact

基线c851204。预期仅assistant_messages.py、main.py具体依赖注入及专属测试；复用ApplicationContent和原admission锁，不修改模型/训练/应用策略。无新增队列、答案表、ACL、恢复器或外部依赖。本次仅规范，独立review后才实施。
