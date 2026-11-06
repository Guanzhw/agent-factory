# Spec Delta

## Purpose

Research支持持续研究交流、有限授权的离线经验回答和真实实验结论复用。它保持原始历史、当前用户纠正与外部操作证据，同时避免内部版本仪式及低于已声明预算的隐藏限制。

## ADDED Requirements

### Requirement: Terminal agreement participates in association
系统 SHALL 从真实终止记录的研究协议中提取目标，即使没有实验，也能按既有权限参与提醒和直接经验复用。

#### Scenario: Stop before experiment
- **WHEN** 研究协议给出目标但在实验前决定停止
- **THEN** 相关任务可检索该停止结论，不因experiment为空丢失关联

### Requirement: Command output obeys one declared budget
系统 SHALL 以已声明的有限输出预算处理命令结果并计入实际序列化开销，不在预算下另加隐藏的12KB上限。

#### Scenario: Ordinary output within allowance
- **WHEN** 命令输出13KB且其完整JSON结果在已声明预算内
- **THEN** 正常取得结果；真正超限时停止归属进程并保留原操作的真实效果状态

### Requirement: Offline answering uses one meaningful consent
离线问答设置 SHALL 允许成员在一个启用动作中选择模型、有限回答额度/期限及关联选项，内部定义发布和精确版本绑定仍可恢复；回答保持无工具且不训练或调用GPU。

#### Scenario: Enable offline answers
- **WHEN** 成员确认模型及有限离线回答额度
- **THEN** 完成必要内部设置并显示可恢复结果，不要求成员分别操作草稿和发布仪式

#### Scenario: Allowance cannot finish one answer
- **WHEN** 新配置或历史配置保存的总额度、每问额度或原任务额度不足以完成实际问答步骤
- **THEN** 在新模型请求前明确拒绝且不提高原保存额度；已经保存的原回复仍可恢复，不产生替代执行

### Requirement: Conversation capacity follows current authorized work
长期研究会话 SHALL 保留原始历史、当前纠正与未知操作证据；普通历史不得因不可压缩的投影或固定寿命轮数永久阻断新用户消息。继续执行仍遵守当前任务明确预算，不因上下文整理自动重置预算或重放未知操作。

#### Scenario: Long conversation with a late correction
- **WHEN** 成员继续已有长会话并给出新的纠正
- **THEN** 新请求可在其授权内继续，模型保留最新纠正与当前任务边界，旧记录仍可查

#### Scenario: Unknown earlier effect
- **WHEN** 历史操作的效果仍未知
- **THEN** 新消息或上下文整理不把它当成停止证明，也不重复执行原操作
