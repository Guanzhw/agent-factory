# Spec Delta

## ADDED Requirements

### Requirement: Readable assistant results retain original meaning

系统 SHALL 将主助手及临时子助手回复的基础Markdown呈现为可读结构，保留代码换行和缩进；真实命令stdout/stderr SHALL 按原文显示，不执行回复中的HTML或自动加载外部图片。

#### Scenario: Read a completed coding task
- **WHEN** 回复包含段落、列表、粗体及代码围栏，工具回执包含真实命令输出
- **THEN** 桌面和手机可辨认结论与代码，代码选择复制后保留原字符，命令输出与模型解释分开

### Requirement: Detail disclosure preserves execution facts

系统 SHALL 允许键盘和触摸展开完整分工目标、子结果、原始ID与回执，保留原任务入口。结果未知及实际失败 SHALL 不因细节折叠或模型自称成功而被隐藏。

#### Scenario: Inspect a long child assignment
- **WHEN** 用户展开分工和结果，再打开原子任务并返回
- **THEN** 原文完整保留、原记录可核对，不创建模型调用或新任务

### Requirement: Stop feedback follows observed state

系统 SHALL 区分停止请求已接收、实际已停止及结果未知；轮询获得后续状态后不得继续以过时提示表示尚未确认停止。

#### Scenario: Stop is later confirmed
- **WHEN** 请求已接收时仍在stopping，随后原会话变为stopped
- **THEN** 初始不宣称已停止，后续显示已停止且不残留等待确认提示

#### Scenario: A command result remains unknown or failed
- **WHEN** 模型正文声称成功，但实际操作仍UNKNOWN或非零退出
- **THEN** 界面保留真实状态、失败退出码和核对原操作入口，不以模型正文覆盖
