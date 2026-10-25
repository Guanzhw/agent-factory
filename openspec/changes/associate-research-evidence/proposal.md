# Proposal

## Why

稳定助手和私有QA已具备原消息、双方证据及操作额度边界，但研究开始/结果事件尚不会定向联系相关助手，当前研究决定也只接原轮证据。需要补齐已确认的主动关联与source→decision→action，不用消息数量冒充团队经验价值。

## What Changes

- 在既有精选研究start/terminal发布事务中写P3事件，依据当前可读相关原记录选择少数已明确启用关联的助手；无匹配不发送，不另建worker。
- 复用固定tool-free QA组件及原scope/原任务，用事件输入生成有出处、明确标为agent分析的领域关联；普通私问继续只写core原reply，两者不互相发布或反向send。
- 关联保存完整实际输入依赖；读权逐源委托core。公开content只包含原事实和必要opaque引用，不复制无法随来源撤回隐藏的派生分析。
- 仅在真实研究轮次实际使用peer证据时持久其适用性决定与原实验动作关联；不普遍增加与本轮无关的decision框架，不改原UNKNOWN恢复。
- 最小应用HTTP和B02入口支持查看关联、来源不可用状态；A08确定性验收与C02/C03真实价值评价分开。

## Capabilities

### New Capabilities

- `research-evidence-associations`: 有界事件关联、当前来源依赖和研究动作出处。

### Modified Capabilities

无归档能力替换；在活跃研究应用/QA规范上增加具体consumer，复用P3而不重定义通用消息协议。

## Impact

基线`76fc1c3`，仅本地spec；实现预计限applications/research、其测试和既定研究UI，部署仅更新固定component pin。没有新coreport、ACL/vault、向量库、轮询恢复器、自动GPU授权或真实外部调用。BYOK仍仅finite rounds/toolCalls/deadline，token/费用未计量，不支持的硬上限明确拒绝。正式C02/C03模型/任务/费用条件和D资源未冻结，仍BLOCKED。
