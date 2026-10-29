# Proposal

## Why

个人 Research 已能读、搜、精确修改源码并运行普通测试，但主线明确拒绝原生 Windows 工作区和 CLI；不用 WSL 的用户无法完成编码任务。复用已有 Windows Job Object 与原 Research 工具/效果记录，补通一个真实文件修改和测试闭环。

基线：`b6c383a5c5543fd0cf7d8c08c043ee8ad0f69abe`。代码为已实施候选；准确提交的验收结果记录在 Draft PR 与关联 CI 中，分开标明云端 Linux、Windows CI、本机 Windows/隔离 PG 重启、浏览器/真实模型。不能据 Linux 回归或通用 CI 汇总宣称其余层已通过。

## What Changes

- Windows 支持现有 owner/session 工作区内 UTF-8 读、字面搜索和精确编辑，保留相对路径、链接拒绝、唯一匹配与哈希回执语义。
- 普通 CLI 在 Windows 复用 `WindowsSSHProcess` 的挂起创建、Job 归属和恢复执行，补 stdin/stdout/stderr、明确环境、cwd、退出码、取消与原 Job 的整树停止证据。
- 沿用 Agno 3.1.0、预算、权限、effect reserve/complete 与 UNKNOWN 不重放；无需新执行引擎或效果状态。
- 分开记录 Linux 回归、真实 Windows 文件/命令闭环、stop/服务硬退出重启验收；未执行的项目保持未验证。

## Capabilities

### New Capabilities

- `research-native-windows-workspace`：原生 Windows 个人 Research 工作区文件和普通命令的执行、停止与原操作恢复。

### Modified Capabilities

无。当前 `openspec/specs` 没有已归档能力；此变更延续既有 Research 工具行为。

## Impact

允许产品文件：`applications/research/session_tools.py`、`platform/agent_factory/_personal_cli_process.py`、`platform/agent_factory/windows_ssh_process.py`；确有 Windows 系统目录/临时目录/UTF-8 需要时，小改 `platform/agent_factory/personal_cli.py::_environment`。文件操作保持 Research 所有，不新建通用文件系统/执行器框架或第二套 Job Object。

允许配套：`applications/tests/test_research_session_tools.py`、`applications/tests/test_research_sessions.py`、必要的同目录 `test_research_windows_restart.py` 隔离进程夹具；`platform/tests/test_personal_cli_process.py`、`test_personal_cli.py`、`test_windows_ssh_process.py`；`README.md`、`docs/DEVELOPMENT_CHECKS.md`、本变更文档。无依赖升级、schema/API/登录/模型配置改变。

不包含 PTY、WSL、远端自由编码、GPU、多团队编排、OS 沙箱保证、安装依赖、新模型/账号/TLS/本机信任、部署或发布。现有工作树和数据库保持原状；本轮云端不操作用户设备或调用外部模型。
