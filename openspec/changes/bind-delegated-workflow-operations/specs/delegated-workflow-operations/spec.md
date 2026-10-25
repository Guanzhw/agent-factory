## Purpose

让受控原生工作流以既有操作身份等待临时委派任务，并在丢失回执、重启或授权撤回时仍能核对与停止原效果；保留父预算、子树停止证明与原生恢复责任，不新增执行或凭据控制链。

## ADDED Requirements

### Requirement: 操作绑定唯一原child
系统 SHALL 将原操作唯一关联到原parent下的child请求，重复或不确定回执不能创建替代child，输入变化必须拒绝。

#### Scenario: 并发或重复启动
- **WHEN** 同一原操作以相同输入再次进入已有准入边界
- **THEN** 只对应同一child/task与预算祖先关系，不产生第二native派发

#### Scenario: 原输入冲突
- **WHEN** 同一操作改用不同goal或mode
- **THEN** 拒绝冲突，不更换请求身份或创建新child

### Requirement: 未知只核对原身份
系统 SHALL 在操作或child回执未知时只查询原持久关联，不通过lookup重新创建或派发任务。

#### Scenario: 回执丢失及缺失关联
- **WHEN** 原create响应丢失、原link尚无child或原native回执缺失
- **THEN** 核对同一原身份并保持UNKNOWN，lookup的create/dispatch计数为零，缺失不被当作停止证明

### Requirement: 停止证明限定child子树
系统 SHALL 根据原child及其后代的实际运行与效果事实判断停止，不将父task持有当前操作造成的等待纳入该子树判断。

#### Scenario: 父操作仍open而child已停止
- **WHEN** 原child子树均已正向停止且父操作尚未关闭
- **THEN** 返回该child子树allStopped并可关闭原操作，不出现父操作等待自身关闭的循环

#### Scenario: 子效果未知
- **WHEN** child native已结束但仍有未解效果或未确认停止的后代
- **THEN** 原操作仍未闭合，不因进程结束或cancel回执伪造停止

### Requirement: 撤权后的原custody清理
系统 SHALL 在核对原操作、parent/run/plan与child绑定后允许原效果观察/取消，同时拒绝撤权后的新执行或跨身份操作。

#### Scenario: 成员禁用或父授权结束
- **WHEN** child已存在且成员被禁用、父停止或scope被取消
- **THEN** 原child可被观察/请求停止，下一新模型/工具入口被拒绝，不能newcreate或恢复执行授权

#### Scenario: 交换句柄或跨owner
- **WHEN** 观察/取消携带其他操作、parent或owner的child句柄
- **THEN** 拒绝且无取消/dispatch副作用

### Requirement: 原生等待恢复传递实际结果
系统 SHALL 沿原工作流、operation与requirement恢复既有等待，使后续模型步骤接收实际child结果而非编造成功。

#### Scenario: 暂停后服务重启
- **WHEN** 工作流实际进入原生等待后服务重启，原child随后产生结果
- **THEN** 沿同一原operation/child/requirement继续，实际输出进入后续模型步骤，重复核对不产生新child

### Requirement: 本地机制不扩大远程权限
系统 SHALL 保持当前明确支持的本地child范围，不通过适配器输入开启未支持placement或建立新凭据链。

#### Scenario: 传入未支持placement
- **WHEN** 请求包含远程placement或额外owner/parent/凭据字段
- **THEN** 在新增执行之前拒绝，不绕过现有资源准入；本地合成验证不被报告为真实GPU或模型自主验收
