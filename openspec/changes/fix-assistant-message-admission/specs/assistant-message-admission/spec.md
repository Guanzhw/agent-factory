# Spec Delta

## Purpose

让成员助手的消息在共同的新任务准入边界复核当前资格及原请求，暂时拥塞恢复后仍能继续原消息，同时保留原执行身份和未知结果的观察职责。

## ADDED Requirements

### Requirement: 任务容量不足保留原交付
系统 SHALL 为活跃任务容量不足返回 HTTP 429 与 `ACTIVE_TASK_CAPACITY_EXHAUSTED`，事件交付保持 pending，保留同一 event/delivery/message/request/allocation，并经既有扫描在容量恢复后继续原准入。

#### Scenario: 真实容量耗尽后恢复
- **WHEN** 接收者达到既有活跃任务上限，事件消息已持久但尚无 task，随后容量释放
- **THEN** 首次记录容量错误和 pending；后续扫描绑定同一 allocation/request 至一个 task，最多一次 native dispatch

#### Scenario: 已有 UNKNOWN 或 reserved 原任务
- **WHEN** 原 task 已存在且回执未确定，即使容量恢复、再次扫描或端点被停用
- **THEN** 只观察原 task，不重新取得 fresh 或发送第二次 native dispatch，不释放未知费用或 custody

### Requirement: 所有新消息共享当前权限与原请求复核
系统 SHALL 在新 task reservation 时，不论端点是否配置 automaticBudget，复核 recipient owner、sender 当前成员资格、端点 enabled 与原 prepared plan/request 的完整指纹。仅预算 scope、caps、allocation 等约束以预算配置为条件。

#### Scenario: 准备窗口内停用端点或发送者
- **WHEN** 无预算消息已保存并准备 plan，在最终新任务准入前端点或 sender 被禁用
- **THEN** 拒绝新 task 和 native dispatch，保留原 message/request

#### Scenario: 无预算消息使用不相干或被篡改的请求
- **WHEN** 新消息原请求被搭配其他 owner、plan 或不同 prepared 指纹准入
- **THEN** 拒绝并且不创建 task

#### Scenario: 停用后的既有任务
- **WHEN** 原 task 已准入后端点停用，再次恢复或读取消息
- **THEN** 继续观察原 task 和既有清理，不因 fresh gate 重派或伪造停止
