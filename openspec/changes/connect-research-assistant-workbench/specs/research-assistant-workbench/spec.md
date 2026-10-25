# Spec Delta

## Purpose

让成员在已确认研究工作台中管理持续身份的个人研究助手，并向明确选择的助手提出私密经验问题。界面依据实际后端状态呈现原请求、操作额度和当前可读证据，不伪造回答、聊天历史或费用保障。

## ADDED Requirements

### Requirement: Explicit personal assistant configuration
界面 SHALL 显式创建个人研究助手并通过私人草稿、明确发布和操作额度确认配置问答；只读取时不得产生写入或模型调用。

#### Scenario: Empty account and unavailable resources
- **WHEN** 没有助手、可用模型连接或QA发布版本
- **THEN** 显示准确空状态及实际创建/资源入口，不自动选择provider或构造默认pin；配置/发布不等于问答执行

#### Scenario: Published QA and honest allowance
- **WHEN** 成员发布QA草稿并确认问题次数、工具操作额度、每问上限与截止时间
- **THEN** 使用精确applicationRef及本人连接，显示操作额度受限且token/费用未计量；不提供声称生效的token/金额硬限额

#### Scenario: Concurrent configuration
- **WHEN** expectedRevision落后或资源/额度已不可用
- **THEN** 显示真实拒绝原因并要求读取最新配置，不自动续额、新建scope或用新revision静默重试

### Requirement: Private directed questions with original recovery
界面 SHALL 仅向用户选择的一个真实助手发送问题，并保留原问题身份恢复；无回答时不得伪造助手文本或任务终态。

#### Scenario: Lost response then reload
- **WHEN** 问题POST遇408、网络或5xx未知应答后刷新，或接收者更换配置
- **THEN** 原sender使用同requestId/peer/text恢复，禁止新键重发；换owner不能读取旧pending或答案

#### Scenario: Original acknowledgement and later read failure
- **WHEN** 已收到问题ID而后续GET失败
- **THEN** 保留原问题URL并仅核对原问题，不重新发送；delivery状态与reply状态分开呈现

#### Scenario: Selected peer and absent history
- **WHEN** 成员浏览分页助手目录、提问并重新访问原问题
- **THEN** 只使用真实目录与原消息，不能广播给所有成员或编造历史对话/相关性推荐；同事配置/凭据不出现在目录

### Requirement: Current source authority and evidence labeling
界面 SHALL 将回答标为agent分析，将全部contentIds标为输入依据，并在重新读取时按当前授权显示完整派生回答。

#### Scenario: Uncited dependency withdrawn
- **WHEN** 原问题重读返回source_unavailable，或依据读取拒绝
- **THEN** 清除旧答案与来源缓存，隐藏整个派生回答而非只删某个链接，不显示浏览器保存的旧答案

#### Scenario: Pending or failed read
- **WHEN** reply为null、重新核对中或读取失败
- **THEN** 分别显示未取得回答、正在核对或明确错误，不能将原task存在/完成推断为科学结论；错误后不保留旧答案正文

### Requirement: Stable platform and project navigation
界面 SHALL 复用平台身份、导航与既有布局，助手配置/私问的深链、资源往返和新项目关联不得重解释旧项目字段。

#### Scenario: Resource and identity round trip
- **WHEN** 从助手配置去模型资源后返回、刷新、后退或退出重登
- **THEN** 恢复原配置/问题ID及成员上下文；平台主页保持独立，无研究应用时core登录/主页无助手死链接

#### Scenario: Stable identity association
- **WHEN** 创建项目选择个人研究助手或读取旧项目
- **THEN** 新项目提交researchAssistantId；旧assistantId继续表示原endpoint，不隐式迁移或造个人助手
