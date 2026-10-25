# Tasks

## 1. 原身份与预算接入前置

- [x] 1.1 root审阅design中的原请求恢复证明及allocation可信口，独立审查spec是否过度设计；用明确结论记录可实施范围与reserved无回执恢复BLOCKED，不把schema valid当验收。
- [x] 1.2 root显式装配单一LocalBudgetScopes及既有guard，实现allocation_id可信参数贯穿ApplicationRuns/FactoryAPI/reserve_task；在原reservation事务内绑定，真实PG测试绑定异常整体回滚、同task同allocation幂等及换scope拒绝（A03/A04）。
- [x] 1.3 实现仅无task消息的可信原request重入，保持公开重复POST只读；用真实PG/native屏障测试双恢复者均先读到无task、旧发送者暂停后恢复、预留提交后/bridge前crash和native丢ACK，证明dispatch最多一次、UNKNOWN不重派（A03）。

## 2. 事务事件与有界订阅

- [x] 2.1 实现同领域事务emit/producer幂等及不透明内容引用，测试回滚双方不可见、提交后进程退出仍有intent、相同键异内容冲突；记录最小应用接入示例（A04）。
- [ ] 2.2 实现owner订阅、候选交集、TTL/depth和current content权限；测试不匹配零准入、撤回旧handle拒绝、禁用成员、根/深度不可由消息重置和循环在scope边界终止（A02/A04/A08）。
- [x] 2.3 实现event/endpoint唯一投递及receiver scope allocation，测试并发额度耗尽、重复仅分配一次、未知用量持续hold、既有settle重复不多结算；明确BYOK/unmetered限制（A04）。

## 3. 离线交付维护与集成

- [x] 3.1 显式装配有界交付维护任务，只投消息/查原收据/调用已有结算，测试native ready后启动、停止新交付后的关闭期限、批次公平扫描和晚提交事件不丢（A01/A04）。
- [ ] 3.2 接研究应用记录/定向经验消费者，真实PG验证领域记录与outbox同连接、离线端点进入既有queue；合成QA测试训练/GPU dispatch为零，不冒充C03真实模型质量（A05/A08）。
- [ ] 3.3 作者之外审查完整base/head diff含spec与所有改动、整改复审；串行运行相关PG/静态/独立core与必要集成，保存首失败和exact-head证据，真实C/D缺参数维持BLOCKED/NOTRUN。

## Workflow follow-up

- 仅在实现与验收完成后归档；本次只完成设计，未执行上述实现或测试。
- reserved/no native receipt窗口不能自动补派；后续若需要更强恢复，须单独提出可证明契约，不在本change暗加重试。
