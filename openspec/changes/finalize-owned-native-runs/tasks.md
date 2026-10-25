# Tasks

## 1. 精确消费者与事务边界

- [ ] 1.1 实现完整nativeComponent pin附加owner选择，保留其他binding/effect owner；测试组件被多个成员应用复用、与工具owner共存、旧声明缺hooks和普通core不命中，记录实际撤装配边界。
- [ ] 1.2 实现原observer的整个已停止group完成事务及同步finalize_original回调，按root→admission→具体namespace→usage锁顺序；真实PG证明terminal/storage/reclaimed/settlement/outbox共同提交，HELD与回调异常共同回滚，无新worker/通知表。

## 2. 旁路与观察事实

- [ ] 2.1 封闭reserve快捷terminal和admission_failed绕过，声明消费者保留给observer且reserve不倒序取root锁；实际入口测试证明无提前释放，未声明core行为保持。
- [ ] 2.2 分开持久正向停止结果与finalizing投影，禁止用task_held/ended_reason表达账务等待；测试成功停止后scope到期、取消/失败收尾及UNKNOWN用量，不丢观察、不改原结果、不生成新执行。

## 3. 故障验收与审查

- [ ] 3.1 串行真实PG验证事务故障点、并发observer/reserve、成功回执丢失与服务重启；原finish_attempt结算后由既有tick仅提交一次outbox，原task/child/operation身份及累计预算不变。
- [ ] 3.2 独立审查完整base/head diff和spec是否过度设计，必要整改后复审；运行受影响静态/架构/适用集成检查并记录首次失败、命令、计数、清理和精确head，不把合成消费者算作真实研究模型验收。

## Workflow follow-up

- coordinator核对证据后才勾选任务；研究应用后续接入另在其change推进。当前仅spec准备，不代表端口已实现。
