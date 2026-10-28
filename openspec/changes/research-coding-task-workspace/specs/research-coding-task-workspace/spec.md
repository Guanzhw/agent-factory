# Spec Delta

## Purpose

成员在明确仓库副本和已准备环境中完成真实代码问题，核对结果并可纠正、停止、返回原会话继续。不把工具存在或脚本模型通过当自主代码工作已完成。

## ADDED Requirements

### Requirement: Work on an explicit repository copy

系统 SHALL 在会话目录内使用成员明确指定公共来源/版本的副本，并由助手提供真实目录、origin、commit 与源码 SHA 回执；副本可由操作方明确准备，不能把该步骤冒充公网 clone 或自动 fallback。沿用所有权/凭据边界，不覆盖原仓库或暗换目录，不将宿主权限执行称 OS 沙箱。不要求新增仓库管理页面。

#### Scenario: Start a real repository task
- **WHEN** 成员提供公共 URL/commit 与代码问题，本环境公网 Git 连接失败，操作方提供已核官方副本到会话目录
- **THEN** 助手用现有命令实际核 pwd、origin、HEAD 和源码 SHA；操作方随后准备隔离 venv editable 指向该副本，主/测试子进程导入路径可核，同一 session 显式继续；本地准备不计作公网成功，不声称自动配环境

### Requirement: Complete ordinary source changes and project tests

系统 SHALL 支持任务所需正常源码的读取、定位、精确修改，包括大于 12KB 的源码，并执行真实项目测试；整文件大小不与单次返回预算混同。超出实际返回预算须明确反馈，不静默省略后声称已完整读取。

#### Scenario: Fix a real project defect
- **WHEN** 任务需修改 45,599 字节正常源码并执行官方回归
- **THEN** 助手先复现失败，再定位修改源码，官方新增回归测试保持原字节；目标与项目完整测试通过须有真实 exit 0 和工具回执

#### Scenario: Search ordinary source beyond 12KB
- **WHEN** 搜索文本实际存在于大于 12KB 的正常源码
- **THEN** 搜索包含该文件的真实匹配，不因尺寸跳过而返回无截断的空结果；编辑不因整文件大于旧限制拒绝，不改未选中的内容

#### Scenario: Real tests exceed the old time limit
- **WHEN** 基线证明正常完整测试超过 30 秒，部署已配置足够操作预算
- **THEN** 测试在真实预算内完成且可停止；不插入等待、换空测试或删用例冒充通过

#### Scenario: Use the normal service entrypoint
- **WHEN** 维护者通过正常启动环境配置现有操作/原生时限，成员创建新会话
- **THEN** 真实服务遵守该配置，新会话默认使用部署操作时限，成员无需每次调整高级参数；旧会话预算不被回写

### Requirement: Make execution results actionable

系统 SHALL 在原任务展示命令、输出、退出/停止状态和文件变化，准确说明未完成/未知及下一步；复用既有结果界面，不要求用户理解内部 effect。

#### Scenario: Inspect failure or uncertainty
- **WHEN** 测试非零退出、工具返回失败或原结果未知
- **THEN** 用户能核实际依据和文件变化，知道可纠正/继续还是需核原操作；未知不得显示为成功

### Requirement: Correct and stop the real task

系统 SHALL 保存中途纠正并在下一次模型请求纳入，显示真实生效时点；停止 SHALL 作用于原运行及受管父子进程，区分已请求、确认停止与未知，不自动复活任务。

#### Scenario: Correct then stop during execution
- **WHEN** 用户在真实项目测试运行时提交约束并请求停止
- **THEN** 纠正保存且不宣称改写在途命令；核原父子进程终止，未确认时保留未知，不只改变 UI

### Requirement: Reopen the same session without replaying uncertainty

服务重启后系统 SHALL 保留原 session、仓库、纠正和操作记录；GET 不创建执行，用户显式继续前核对原操作，未知副作用不换 ID 重放，重复点击不重复启动。

#### Scenario: Restart and explicitly continue
- **WHEN** 服务退出后用户返回原会话
- **THEN** 原目标、改动与执行事实可核对，读取不执行；确认可继续后显式创建下一轮，未知操作仍阻止盲目重放
