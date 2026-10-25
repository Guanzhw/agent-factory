# Spec Delta

## Purpose

让应用沿既有双方私密消息保存原接收任务的回复，不再通过反向发送启动另一个执行。回答引用共享内容时持续尊重双方当前读取范围，撤回不泄漏派生摘要，也不删除原问句或历史执行身份。

## ADDED Requirements

### Requirement: Original task reply exactly once
系统 SHALL 仅允许可信原接收任务为原消息提交一次有限回复；相同重试幂等，不同回复冲突，不增加消息、任务或预算分配。

#### Scenario: Same original reply retry
- **WHEN** 原接收任务两次或并发提交相同正文和同一规范来源集合
- **THEN** 只有一个原回复且无额外dispatch/allocation，重复读取相同内容

#### Scenario: Foreign task or conflicting reply
- **WHEN** caller用另一owner/task或普通非消息task回复，或修改已提交回复
- **THEN** 明确拒绝，原消息和回复不变

### Requirement: Current shared source intersection
系统 SHALL 在提交时验证双方当前成员及每个不可变内容引用对双方可读；来源数量和正文沿现有限额，允许空来源普通回复。

#### Scenario: Private or invalid source
- **WHEN** 原receiver可读但sender不可读来源，或来源不存在/任一方禁用
- **THEN** 不持久化回复，不把对方私有证据复制到消息

#### Scenario: Plain bounded reply
- **WHEN** 原任务提交合法限长正文且无来源，双方当前有效
- **THEN** 原消息双方可读该回复，第三方仍不可读

### Requirement: Withdrawal hides derived reply
系统 SHALL 将提交/读取与来源撤回串行；任一来源或双方成员当前不可用时隐藏整个派生回复，保留原问句与原收据，不创建执行或改变持久状态。

#### Scenario: Withdrawal commits before reply or read
- **WHEN** 来源撤回先提交，随后提交回复或读取已存回复
- **THEN** 新回复拒绝；旧回复投影source_unavailable且不含正文/来源，原问句仍按原权限可读

#### Scenario: Authorized snapshot precedes withdrawal
- **WHEN** 合法回复提交或读取先取得串行边界，随后撤回
- **THEN** 该合法快照可完成；撤回后的新读取隐藏回复，已交付字节不承诺远程撤销

#### Scenario: Sharing restored
- **WHEN** 同一来源恢复共享且双方当前可读
- **THEN** 原回复重新可读，不生成新任务或新回复

#### Scenario: Disabled receiver preserves sender original receipt
- **WHEN** 已回复后接收者禁用，仍有效的发送者读取原消息、原请求或重复发送原命令
- **THEN** 原问句及原执行收据可读，回复source_unavailable且零dispatch；公开应用运行接口仍拒绝被禁用接收者，不能伪造unconfirmed

### Requirement: Preserve old message data
系统 SHALL 对既有数据进行非破坏性可重复迁移，未回复消息保持原问句/收据及幂等身份，增加空回复投影。

#### Scenario: Existing database restarted
- **WHEN** 升级有旧消息和命令的数据库并重复启动
- **THEN** 旧数据不变、reply为null，原重复POST不派发，新增回复可按新契约保存
