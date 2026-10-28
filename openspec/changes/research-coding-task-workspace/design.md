# Design

## Context

底座基线 `da2b6ca0ef0bf60062721b2c0a1755d3434e8da2`，保留 Agno 3.1.0。任务选官方 pytest-dev/pytest-asyncio [问题 #1040](https://github.com/pytest-dev/pytest-asyncio/issues/1040)、[PR #1051](https://github.com/pytest-dev/pytest-asyncio/pull/1051)：修复前 commit `2188cdbbf7b47e653957d3f39aeb7d4d0de80bf4`，仅加入官方 release 修复 `7c501923b00b4aeeb68d4b3b11065f0c3b5cba2c` 的回归测试增量；未人为改坏源码。

| 证据 | 实际结果 | 不能据此声称 |
| --- | --- | --- |
| 直接目标回归 | exit 1；teardown `RuntimeError: Event loop is closed`；1.417 秒 | Agent 已自主定位 |
| 原命令 `coverage run -m pytest` | 204 passed / 2 failed，33.802 秒，日志 10,847 字节 | 命令输出上限已触发 |
| 独立官方修复参考 | 206 passed / 0 failed，35.094 秒 | Agent 自己修好了；参考答案不得预喂模型 |
| 原生 Research + 脚本模型 | 小文件和目标回归可运行；45,599 字节 `plugin.py` 读取/编辑被拒 | 真实模型自主闭环通过 |
| 正确查询补验 | 236 字节小文件首行命中；大文件已确认存在的首行搜索却返回空、truncated=false | 旧错误查询证明漏搜 |
| 原生完整测试 | 31.096 秒，`PERSONAL_CLI_TIMEOUT`、unknown、stopped=true；会话 blocked，effect UNKNOWN | 测试完成、可重试或完整父子停止已验；本次仅记录父 PID 消失 |

证据根目录 `/workspace/design-audit/research-coding-task-20261028/`：`BASELINE.md`、manifest、目标/完整/参考日志；原生目录 `qa/native-1793205409335388058/` 和搜索补验 `qa/native-search-correction-1793206090586775620/`。旧搜索用例误用下划线，原记录保留为无效查询。0 次真实模型调用。目标源码 SHA256 `41a7b8e0741eac47470096245e07e9baf8ccb3a7556bfbb77b05076010c3a2d1` 未变。Python 3.12.14，pytest 8.3.4、hypothesis 6.123.4、coverage 7.6.10，依赖预装于隔离 venv。

文件 12,000 **字节**限制与会话 12,000 **字符**投影不同。此源码的读取 JSON 约 47,442 字节，低于现有 65,536 工具返回预算，不需提前增加行分页或模型传输容量。部署默认操作 8 秒，Research API/setup/工具又夹到 30 秒；共享 `EnvironmentLimits` 也只接受 0.1–30 秒，直接移除 Research 夹断仍会构造失败。原生一轮默认 60 秒。`Settings.from_env` 未接操作/原生超时，QA 直接构造 Settings(600/120) 不证明正式启动可配置。

## Goals / Non-Goals

**Goals:** 同一个人会话在明确仓库副本和已准备项目环境中读搜改代码、跑完整测试，收到纠正，能停止并在重启后核对、显式继续。先修上述真实障碍。

**Non-Goals:** 新 harness、仓库/依赖管理器、分页框架、第二执行器、全站重画或提高所有上限。无 OS 沙箱/CPU 内存强隔离、PTY、原生 Windows 命令、真实 GPU、30 路容量、长期记忆/动态 teams 完成声明。

## Decisions

1. **仓库与环境明确接入。** 操作方先将既有 `FACTORY_RESEARCH_COMMAND_PATH` 配为预定隔离 venv/bin 与系统 PATH，再正常启动服务。成员目标给公共 URL/commit；用现有 `research_run` 在会话目录内 git clone/checkout，再输出 `pwd`、`git remote get-url origin`、`git rev-parse HEAD`。现有 cwd 回执是相对路径，不能单独代替实际目录。取得副本后，操作方在该 venv 安装官方固定依赖并将项目 editable 安装指向本次会话副本，随后显式继续任务。主进程和 pytest 子进程都须核实际 `pytest_asyncio.__file__`，不得误测旧目录；命令环境经过清理，不依赖环境中的 PYTHONPATH 或测试额外注入。官方回归测试是公开验收输入、保持原字节；原仓库和参考修复副本不在执行范围。这是有预配置步骤的首闭环，不宣称任意 URL 自动可用或助手自动安装依赖，不新增 repo 表、选择器或环境管理器。
2. **整文件与返回预算分开。** `applications/research/session_tools.py` 去除读取和精确编辑对整文件 12KB 的绑定；保留现有最终工具返回预算、路径检查、唯一匹配和前后 SHA。搜索逐行覆盖正常 UTF-8 文件，不按 12KB 大小静默跳过，沿既有匹配/扫描截断反馈。不新增 offset/next/schema 或无实际资源依据的文件魔数；命令输出上限和会话投影不提高。若实模确因返回量/上下文失败，先记录再在同 spec 说明最小修复；不能静默截断并宣称已读完。
3. **只接通已有时间预算。** `platform/agent_factory/config.py::Settings.from_env` 将 `FACTORY_OPERATION_TIMEOUT_SECONDS`、`FACTORY_NATIVE_TIMEOUT_SECONDS` 接到现有两个 Settings 字段，保留 core 的 8/60 默认；操作值遵循平台 Budget 的 1–600 秒边界，原生时限沿既有 60–3600 秒校验，不加配置体系。`platform/agent_factory/execution_bindings.py::EnvironmentLimits` 的超时描述范围上限对齐已有 600 秒预算，保留其默认和其他 adapter 自己的实际时限；回归验证不能因共享描述范围改变而隐式增大其他执行时限。`session_routes.py` 采用同一 600 秒 schema 边界；`session_setup.py` 与 `session_tools.py` 去掉重复 30 秒夹断，服从持久化原计划和部署预算。新会话默认使用部署已配置操作时限，成员不用每次展开高级输入；旧会话不改预算或重启操作。验收启动配置为操作 60 秒、原生一轮 300 秒，覆盖已测 35 秒完整测试及本任务模型/工具开销，是此部署配置而非容量保证。通过正常 `agent-factory-research` 启动路径验证，不能只改测试 Settings。
4. **复用反馈与控制。** `ResearchSessions.tsx::ToolOutput` 已显示命令、cwd、退出、stdout/stderr 和文件 SHA；仅在真实浏览器发现必要状态缺口时修此处，不新造结果组件。沿用 corrections/stop/turns/request 与 effect；纠正在下一模型请求生效，不改写在途命令。GET 不执行，显式继续先核原操作；超时 UNKNOWN 不因进程消失就变成成功或自动重跑。ui-ux-pro-max 的就地错误/异步反馈、impeccable clarify/distill 的“发生什么/下一步”与默认值原则用于任务状态，内部回执保留折叠。

## Acceptance sequence

1. 正常服务入口加载上述配置；真实登录进入独立 Auto Research 个人会话，目标含公共仓库/commit、缺陷及“保留测试、通过后停止”。取得并核副本、明确完成环境预置后，助手先复现官方回归，再自主读搜改源码，目标与完整测试均须真实 exit 0；不改官方测试、原仓库，不接触参考答案。
2. 在同一任务真实测试期间提交纠正，核保存及下一模型请求纳入时点；请求停止并记录实际测试父子 PID/进程组及终止结果。未确认时保留未知，不以 UI 代替进程证据。
3. 实际服务退出后重启，返回原 session、仓库和文件变更；GET 不执行，核原请求后显式下一轮继续。重复提交只产生一次执行；未知原操作不得换 ID 重放。桌面/手机能看懂失败、文件变化和下一步。

确定性工具/进程回归、真实 PostgreSQL 原生运行、脚本模型、获准 Go 模型自主完成和浏览器分别列结果。已有基线不抵扣上述验收；先沿现有调用次数，必要时同会话分轮，不预增预算。

## Risks / Trade-offs

- [宿主权限与环境预置] → 如实说明本机执行边界及操作方准备步骤，不称沙箱或自动项目配置；真实 SSH/GPU 未测。
- [执行退出结果未知] → 保留原回执与阻塞，不用新请求“恢复成功”；只按已知可继续状态显式续接。
- [新实际瓶颈] → 保留失败再修最小点，不加收费 fallback、多版本兼容或策略层。

## Migration Plan

不变更数据 schema、Agno 版本或旧会话持久预算，不重放历史任务。先独立评审、Draft 与准确 head full；PR153/154/155 的 Ready 专项许可仍 pending，不绕过发布门禁。上线前在实际目标核对在途操作与配置；没有目标部署完成声明。
