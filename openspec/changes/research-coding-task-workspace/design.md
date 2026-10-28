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

证据根目录 `/workspace/design-audit/research-coding-task-20261028/`：`BASELINE.md`、manifest、目标/完整/参考日志；原生目录 `qa/native-1793205409335388058/` 和搜索补验 `qa/native-search-correction-1793206090586775620/`。旧搜索用例误用下划线，原记录保留为无效查询。上述脚本基线为 0 次真实模型调用。目标源码 SHA256 `41a7b8e0741eac47470096245e07e9baf8ccb3a7556bfbb77b05076010c3a2d1` 未变。Python 3.12.14，pytest 8.3.4、hypothesis 6.123.4、coverage 7.6.10，依赖预装于隔离 venv。

文件 12,000 **字节**限制与会话 12,000 **字符**投影不同。此源码的读取 JSON 约 47,442 字节，低于现有 65,536 工具返回预算，不需提前增加行分页或模型传输容量。部署默认操作 8 秒，Research API/setup/工具又夹到 30 秒；共享 `EnvironmentLimits` 也只接受 0.1–30 秒，直接移除 Research 夹断仍会构造失败。原生一轮默认 60 秒。`Settings.from_env` 未接操作/原生超时，QA 直接构造 Settings(600/120) 不证明正式启动可配置。

真实模型验收前，Research 等价净化环境（PATH/LANG、临时 HOME，无代理凭据）执行官方仓库 `git ls-remote ... HEAD`，5.041 秒后 exit 128，`Failed to connect to github.com port 443`；原件 `qa/live/public-git-preflight.json` 保留。随后同一 `/usr/bin/git` 在普通环境只读访问成功，说明本片研究命令环境缺少当前出口配置，而非云端整体不通或政策拒绝；代理/CA 的逐项因果仍未验证（`qa/network-audit/README.md`）。本片不修改网络代码或透传配置；研究命令公网 clone 仍未通过，本地副本不抵扣。

在 oracle 的同一项目/venv 对照中，editable finder 无 PYTHONPATH 时引入 `PytestAssertRewriteWarning`，导致原测试的 warnings=0 断言失败；带 PYTHONPATH 时通过。改用普通 venv 内明文源路径 `.pth`，仅 PATH/LANG/HOME/TMPDIR 下目标回归 exit 0、1.37 秒、无该警告（`qa/editable-warning-diagnosis/source-pth.json`）。这是项目测试发现环境问题，不是待修 bug；原失败保留，不改测试或产品来掩盖。此对照仅证明目标回归，最终会话副本的完整测试仍须重验。

候选 `b8aa252ce747d31d182fc69f5bef220910835168` 的首轮真实 Go 为 1 次 HTTP 200（glm-5.3-flash），返回同轮合法 `pwd`、`ls -la` 两个 `research_run`。Agno 3.1.0 的 async gather 同时调用它们；第二个把第一个正常在途 effect 当 UNKNOWN，整轮 stopped。pwd 随后 exit 0/DONE，ls 未启动，无遗留 UNKNOWN、允许显式 start；未到修复或 pytest（`qa/live/run-1793207318373398063/diagnosis.json`）。已有 `parallel_tool_calls=False` 仍未阻止该响应；固定版本无可用执行串行开关，不能靠提示禁并行处理此实际失败。

同一 head 的 `parallel-diagnosis/baseline-replay.json` 已用该真实双工具响应、1 次脚本模型、实际临时进程重现 pwd DONE/ls 未启动，0 次 Go。此最小复现直接使用 Agno Agent 与内存 authority/store，raw 状态为 completed，不能称 PostgreSQL 平台失败；完整平台失败仍取上述真实 Go 证据。固定安装源码 SHA 与无串行开关核查保存在同目录 `agno-source.json`。

## Goals / Non-Goals

后续真实 Go `deepseek-v4.1-flash` 在 `afee072af2a8f163795972c33d5a9e7063fd93d7` 已复现目标测试失败，但 repair 对 `project/pytest_asyncio/plugin.py` 搜索时失败：schema/描述未声明仅目录，实现却用 `_directory` 打开文件。只读调用未 reserve effect，两个先前命令均 DONE，源码未改、无 UNKNOWN。普通 `ValueError` 经 core `protected_boundary` 写 `tool_failed`，随后触发 `protected-failure` 结束原轮。13 次真实请求均 HTTP 200 / Go，原件 `qa/live/run-1793210179073291872/diagnosis.json`；不是模型协议或同轮锁故障。另一次 5 请求运行因 8 工具预算在核仓库后耗尽，QA 错误要求首轮已复现而结束，保留为验收脚本失败；修订允许同 session 有限显式继续，不能称无需用户续轮。

**Goals:** 同一个人会话在明确仓库副本和已准备项目环境中读搜改代码、跑完整测试，收到纠正，能停止并在重启后核对、显式继续。先修上述真实障碍。

**Non-Goals:** 新 harness、仓库/依赖管理器、分页框架、第二执行器、全站重画或提高所有上限。无 OS 沙箱/CPU 内存强隔离、PTY、原生 Windows 命令、真实 GPU、30 路容量、长期记忆/动态 teams 完成声明。

## Decisions

1. **仓库与环境明确接入。** 操作方先将既有 `FACTORY_RESEARCH_COMMAND_PATH` 配为预定隔离 venv/bin 与系统 PATH，再正常启动服务。成员目标给公共 URL/commit；本环境由操作方把已核官方来源与版本的公共仓库副本提供到该会话目录。助手仍通过真实 `research_run` 输出 `pwd`、`git remote get-url origin`、`git rev-parse HEAD` 和目标源码 SHA，核对原 manifest；现有相对 cwd 回执不能单独代替实际目录。副本核对后，操作方在该 venv 安装官方固定依赖，并通过标准项目源路径配置指向本次副本（本案例使用 venv 内只含源目录路径的 `.pth`，不执行自定义 finder），核实际导入和 pytest 测试发现后，在同一 session 显式继续。主进程和 pytest 子进程的 `pytest_asyncio.__file__` 均须指向该副本，不依赖 PYTHONPATH、代理或测试 transport 的额外环境注入；不能再把仅 editable 安装记为环境已通过。既有命令工具仍可承载 git clone/checkout，但研究净化路径本轮未通过；不自动切换副本或网络配置。官方回归测试是公开验收输入、保持原字节；原仓库和参考修复副本不在执行范围。这是明确的环境准备，不宣称任意 URL 自动可用或助手自动安装依赖，不新增 repo 表、选择器、fallback 或环境管理器。
2. **整文件与返回预算分开。** `applications/research/session_tools.py` 去除读取和精确编辑对整文件 12KB 的绑定；保留现有最终工具返回预算、路径检查、唯一匹配和前后 SHA。搜索逐行覆盖正常 UTF-8 文件，不按 12KB 大小静默跳过，沿既有匹配/扫描截断反馈。不新增 offset/next/schema 或无实际资源依据的文件魔数；命令输出上限和会话投影不提高。若实模确因返回量/上下文失败，先记录再在同 spec 说明最小修复；不能静默截断并宣称已读完。
3. **只接通已有时间预算。** `platform/agent_factory/config.py::Settings.from_env` 将 `FACTORY_OPERATION_TIMEOUT_SECONDS`、`FACTORY_NATIVE_TIMEOUT_SECONDS` 接到现有两个 Settings 字段，保留 core 的 8/60 默认；操作值遵循平台 Budget 的 1–600 秒边界，原生时限沿既有 60–3600 秒校验，不加配置体系。`platform/agent_factory/execution_bindings.py::EnvironmentLimits` 的超时描述范围上限对齐已有 600 秒预算，保留其默认和其他 adapter 自己的实际时限；回归验证不能因共享描述范围改变而隐式增大其他执行时限。`session_routes.py` 采用同一 600 秒 schema 边界；`session_setup.py` 与 `session_tools.py` 去掉重复 30 秒夹断，服从持久化原计划和部署预算。新会话默认使用部署已配置操作时限，成员不用每次展开高级输入；旧会话不改预算或重启操作。验收启动配置为操作 60 秒、原生一轮 300 秒，覆盖已测 35 秒完整测试及本任务模型/工具开销，是此部署配置而非容量保证。通过正常 `agent-factory-research` 启动路径验证，不能只改测试 Settings。
4. **复用反馈与控制。** `ResearchSessions.tsx::ToolOutput` 已显示命令、cwd、退出、stdout/stderr 和文件 SHA；仅在真实浏览器发现必要状态缺口时修此处，不新造结果组件。沿用 corrections/stop/turns/request 与 effect；纠正在下一模型请求生效，不改写在途命令。GET 不执行，显式继续先核原操作；超时 UNKNOWN 不因进程消失就变成成功或自动重跑。ui-ux-pro-max 的就地错误/异步反馈、impeccable clarify/distill 的“发生什么/下一步”与默认值原则用于任务状态，内部回执保留折叠。
5. **同一 run 的应用工具串行。** 仅在 `ResearchSessionTools` 用 `(owner, task, run)` 的 `asyncio.Lock` 包住原 invoke，获锁后才执行已有 guard、原 effect 检查及 reserve/execute/complete。各 Function 闭包强持相同锁，应用实例用 `WeakValueDictionary` 复用它，函数释放后自然清理；不建永久锁表、持久队列或通用调度器。不同 run 不共锁；旧/异 run UNKNOWN 仍由原持久 effect 拒绝，不因服务重启或本地锁消失而重放。等待期间 stop/撤权时，获锁后的原 guard 拒绝启动；执行中的命令继续走现有取消和父子进程控制。先用真实双工具响应做零 Go 回归重现，再独审此局部变更，不修改 provider 提示来躲过问题。
6. **搜索文件与可纠正错误。** `research_search.path` 接受 workspace 内相对文件或目录，省略时仍查当前目录；复用安全目录/文件打开和现有匹配截断，不新增搜索框架。Research 层将 schema 校验、只读文件目标错误及现有明确未派发的失败回执返回为可读失败结果，记录失败事件但不抛出触发 core `tool_failed` 的普通异常；助手可在原轮剩余额度内自行改参数。现有 `CLIProcessError` 只有 `dispatched=False` 且已结束才为 failed，不能把 stopped 等同无副作用。授权/来源撤销、用户停止、未知/未保存回执及可能已经写入或派发的错误保持原阻断。保留原调用/失败回执，不自动重试，不新增全局错误分类或放宽 core 生命周期。

此失败回执行为也影响现有同事提问工具：已核 `_ask`、`_reserve`、消息/event/intent 共用同一事务，向外抛 HTTP 错误时先回滚，再返回 failed；其中没有外部模型调用。此类已知提交前拒绝同样可纠正，不增加 ask 特例以维持旧的“全部失败即终止”断言。同 call ID 只读取原失败，不重新发送；合法新参数使用新 call，仍受原预算和当前权限控制。当前成员/已用来源撤销、原消息结果未知不属于此分支。局部文件打开/读取阶段的 OS 目标拒绝与平台授权 guard 分开；写入/truncate/fsync 后错误仍为 UNKNOWN。

## Acceptance sequence

1. 正常服务入口加载上述配置；真实登录进入独立 Auto Research 个人会话，目标含公共仓库/commit、缺陷及“保留测试、通过后停止”。本环境先由操作方提供已核官方副本，助手核实际目录、origin、HEAD/源码 SHA，再由操作方准备隔离 venv 的标准项目源路径并核主/子进程导入与 pytest 发现；同一 session 显式继续后，助手先复现官方回归，再自主读搜改源码，目标与完整测试均须真实 exit 0。不改官方测试、原仓库，不接触参考答案；研究命令公网 clone 未通过，不用本地准备抵扣。
2. 在同一任务真实测试期间提交纠正，核保存及下一模型请求纳入时点；请求停止并记录实际测试父子 PID/进程组及终止结果。未确认时保留未知，不以 UI 代替进程证据。
3. 实际服务退出后重启，返回原 session、仓库和文件变更；GET 不执行，核原请求后显式下一轮继续。重复提交只产生一次执行；未知原操作不得换 ID 重放。桌面/手机能看懂失败、文件变化和下一步。

确定性工具/进程回归、真实 PostgreSQL 原生运行、脚本模型、获准 Go 模型自主完成和浏览器分别列结果。已有基线不抵扣上述验收；先沿现有调用次数，必要时同会话分轮，不预增预算。

同轮多工具另作针对性回归：合法双调用均各完成一次；不同 run 不被该锁串行；旧/异 run 与服务重启后的 UNKNOWN 不启动新副作用；停止或撤权时，正在运行的工具按原机制处理，等待者不得随后启动。零 Go 回归仅验证调用与控制协议，不代替恢复真实模型代码任务。

错误恢复另验：原真实单文件搜索参数得到正确行号/片段；正常 native/PG 一轮先收到明确无副作用的参数或文件目标错误，再由模型选择正确参数完成，失败原事件保留且没有 `protected-failure`。对照权限撤回、原 UNKNOWN、取消及可能已经派发的命令仍阻止新增操作。最终实模通过以只读验证阶段的新 target/full 回执和源码前后 SHA 一致为准，不能沿用修改前的测试结果。

## Risks / Trade-offs

- [宿主权限、网络与环境预置] → 如实说明本机执行及操作方准备步骤，不称沙箱或自动项目配置；研究净化环境公网兼容性仍未解决，不将其当成永久安全边界，本片不顺带修改网络；真实 SSH/GPU 未测。
- [执行退出结果未知] → 保留原回执与阻塞，不用新请求“恢复成功”；只按已知可继续状态显式续接。
- [新实际瓶颈] → 保留失败再修最小点，不加收费 fallback、多版本兼容或策略层。

## Migration Plan

不变更数据 schema、Agno 版本或旧会话持久预算，不重放历史任务。先独立评审、Draft 与准确 head full；PR153/154/155 的 Ready 专项许可仍 pending，不绕过发布门禁。上线前在实际目标核对在途操作与配置；没有目标部署完成声明。
