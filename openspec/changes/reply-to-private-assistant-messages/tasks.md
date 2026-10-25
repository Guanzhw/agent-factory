# Tasks

## 1. Contract review

- [ ] 1.1 coordinator及独立reviewer核对原task身份、回复读取与撤回串行、应用消费者签名；通过后才实施。

## 2. Reply storage and projection

- [ ] 2.1 实现nullable JSON兼容迁移和可信reply_for_task；便携验证旧行/重复启动、输入限额、原task隔离、同内容幂等/异内容冲突、空来源回复。
- [ ] 2.2 显式装配现有ApplicationContent；验证双方来源交集、第三方拒绝、撤回隐藏完整正文、原问句保留、重新共享原回复可读，无新增执行/预算/content发布。

## 3. Transaction verification and integration

- [ ] 3.1 串行真实PG用实际装配和确定性屏障验证并发回复唯一、撤回先/回复先/读取先的锁序及事务回滚；记录首失败，不放宽断言或重试追绿。
- [ ] 3.2 独立完整base/head精简review、必要整改复审、适用静态与集成检查；明确合成协议不证明真实模型QA质量或无泄漏策略完成。
