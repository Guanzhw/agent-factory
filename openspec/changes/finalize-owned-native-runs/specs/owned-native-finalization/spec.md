## Purpose

为明确装配的原生应用运行提供可核对的完成边界，使真实停止、预算结算、应用结果记录及后继事件可靠衔接；在未知用量或写入失败时沿原任务观察，不增设执行恢复链，也不伪造已完成事实。

## ADDED Requirements

### Requirement: 原运行事务完成
系统 SHALL 在原root正向停止且相关child/effect停止后，以同一数据库事务提交整个已停止group的terminal、storage释放、原root reclaimed、预算结算及声明消费者的结果/outbox。

#### Scenario: 正常完成
- **WHEN** 原native group已停止且原allocation可结算
- **THEN** 终态、结算、结果及唯一outbox共同可见；原group释放不能早于事务提交

#### Scenario: 回调或提交失败
- **WHEN** 结算后或应用结果写入后回调失败，或事务提交前进程退出
- **THEN** 未提交修改回滚，原root仍可被现有observer核对，不释放原hold或产生可投递后继

### Requirement: 未知用量沿原任务等待
系统 SHALL 在原allocation仍HELD时保留原root待收尾，由现有observer再次核对，不新增任务、通知worker或替代用量。

#### Scenario: 停止后用量未知
- **WHEN** 已正向停止但原provider attempt用量UNKNOWN
- **THEN** 原完成事务回滚、预算保持占用、无successor，仍呈现已停止与结算待核对的区别

#### Scenario: 原证据到达及重启
- **WHEN** 原attempt权威证据完成结算且observer继续或服务重启
- **THEN** 同一原root完成一次结算与outbox，不重跑provider、不换task身份、不依赖新增唤醒hook

### Requirement: 所有终态入口遵守完成责任
系统 SHALL 对已声明完成消费者的原task阻止快速terminal路径绕过完成事务；未声明任务保持现有原生行为。

#### Scenario: 并发准入触发容量清理
- **WHEN** 另一个请求reserve时发现声明消费者的原native ticket已完成
- **THEN** 不直接释放该原task，原完成记录与结算仍由统一边界提交

#### Scenario: 准入被明确拒绝
- **WHEN** 原task已持久但未取得native run即admission_failed
- **THEN** 保留rejected事实，核对无已发生效果后完成原失败记录与实际存在的预算绑定，不伪造成功运行

### Requirement: 完成等待不制造执行custody
系统 SHALL 分离实际停止事实和账务/应用收尾，完成等待不能成为task_held、未解effect或新的取消原因。

#### Scenario: 完成事务延后
- **WHEN** groupStopped成立但结算或应用回调尚不能提交
- **THEN** 原root仍被观察且明确标记收尾待核对，不伪装仍在训练，不进入停止证明与账务等待的循环依赖

### Requirement: 完成回调不拥有执行准入
系统 SHALL 仅向可信装配的原任务消费者提供同步事务完成事实；回调只能写关联记录和outbox，不能submit或替换原执行身份。

#### Scenario: 并发核对或成功响应丢失
- **WHEN** 多个观察者核对同一原root或完成提交后响应丢失
- **THEN** 同一领域完成身份和outbox只提交一次，后继由既有P3按原事件唯一准入

#### Scenario: 非消费者及原消费者不可用
- **WHEN** 普通用户应用未声明完成责任，或原声明消费者在重启后不可用
- **THEN** 按既有nativeComponent完整pin附加选择消费者并保留其他binding/effect owner，不按名称猜测；普通core任务维持原语义，旧pin声明仍存在但hooks不可用时不得绕过，删除全部声明后的自动识别不在承诺内

### Requirement: 正向停止观察独立保留
系统 SHALL 将已确认停止及其原结果类别与账务完成分别持久化，完成事务回滚不能丢失停止观察，后续截止时间不改写原已停止结果。

#### Scenario: 结算等待期间scope到期
- **WHEN** 原任务组已正向停止成功但用量仍HELD，随后scope到期
- **THEN** 原成功停止事实保留，整个group完成事务仍待原用量核对，不把到期写成原执行失败或发新任务

### Requirement: 收尾锁顺序一致
系统 SHALL 沿root、admission、具体应用/content/event namespace、usage顺序完成收尾，不在已进入reserve时倒序获取root锁。

#### Scenario: 回调与并发准入竞争
- **WHEN** 同时发生scope结算、应用outbox回调和另一个任务reserve
- **THEN** 回调的namespace锁已在usage锁前取得；reserve跳过该消费者的快捷terminal，不通过反向root锁阻塞形成死锁

### Requirement: 正向停止关闭原运行的新执行
持久正向停止事实 SHALL 阻止同一root及child的保留模型、工具和新child入口；原身份读取、清理、用量核对和完成事务仍可继续。

#### Scenario: 原用量尚未结算
- **WHEN** 已确认原运行停止但allocation为HELD且task尚未terminal，保留context试图调用模型、工具或新建child
- **THEN** 新工作被拒绝，调用/dispatch计数不增；重启后仍拒绝；observer不将该停止边界或后来的scope到期误判为原成功任务失败，原usage结算后可完成同一事务
