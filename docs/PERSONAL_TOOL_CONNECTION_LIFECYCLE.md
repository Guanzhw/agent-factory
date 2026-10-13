# 个人连接驱动的 CLI / MCP 调用

PR #88 基于已合入的 `main@3ef542ba` 实现本能力。工具、schema 和依赖由部署静态安装；
应用声明工具及连接需求，成员保存本人凭据并绑定一次，后续调用沿原任务中的 owner 与
连接版本自动解析。普通绑定与调用不新增管理员逐次审批。

当前实现包括个人登记与浏览器入口、原生 Agno Function/effect 包装、POSIX CLI 适配器，
以及官方 MCP SDK 的 Streamable HTTP 适配器。验证使用合成认证、本地真实 CLI 进程、
本地 MCP 测试服务器及真实 PostgreSQL/Agno 生命周期。具体外部供应商尚未验收，不能据此
声称已兼容某个商业 CLI/MCP 服务、其账号探测或 OAuth 刷新。合成原生工具循环使用确定性
模型夹具，不调用真实模型或 AutoResearch。

## 成员使用流程

1. 打开“资源 → 我的凭据与连接 → 我的工具连接”，选择已安装的 CLI 或 MCP 工具。
2. 页面显示该工具固定的凭据用途和目标；选择匹配的本人凭据，或通过现有 vault 入口保存。
3. 页面创建个人工具登记并完成已有 user-connection 绑定。两个命令各有原请求回执；
   网络中断后只核对原请求，不换 ID 重发。
4. 在应用装配时选择该连接。模型只提供工具业务参数；owner、连接、凭据版本和目标来自
   可信计划，不能由模型参数替换。后续调用无需再次输入秘密。
5. 撤销连接或轮换凭据后，旧版本不能发起后续调用。需要使用新凭据时显式建立新绑定。
   已发出的副作用不因撤销自动消失；结果不明时保留 UNKNOWN。

配置登记是本地的凭据授权检查，不是远端登录或账号归属验证。适配器必须明确实际凭据
读取来源，并在自己的目标协议中验证所需账号语义。未证明的供应商认证策略不能宣称通过。

中断后，确认尚未发送的步骤可点击“结束未发送步骤”；页面会重新核对账户及原步骤，
保留已保存配置和回执。绑定 POST 明确返回凭据失效、工具撤销或适配器变化/移除时，也会
结束该绑定等待，不重发或替换凭据。真正丢回复、未分类冲突以及恢复查询的 404 仍保留原
请求，只允许核对回执，不能以“尚未查到”推断未执行。

## 静态装配与模块边界

| 层 | 责任 |
| --- | --- |
| Core | 沿用 RunContext、ExecutionBindings、ConnectionService、vault 和 effect；提供工具描述、个人登记、原生 Function 包装与回执。无 research 依赖。 |
| 应用 | 用既有材料、`connectionRequirements` 与 `runtimeBinding.config.connectionName` 声明工具连接；只消费业务参数和结果。 |
| CLI adapter | 固定命令及参数映射、凭据输入、子进程环境与临时状态、输出解析、进程结束证据。 |
| MCP adapter | 固定服务器及工具/schema、异步客户端/session 生命周期、调用与协议取消语义。 |
| 部署 | 显式构造适配器及 vault 用途/目标策略，将实例放入 `Settings.personal_tool_adapters`；不从请求动态导入代码。 |

公共 Python 契约是 [personal_tool_contract.py](../platform/agent_factory/personal_tool_contract.py)：
`ToolDescriptor` 描述 adapter ID/revision、原生工具名、输入 schema、transport、凭据用途/
目标、capabilities、权限及 read-only policy；`PersonalToolAdapter.invoke(ToolInvocation)`
执行一次调用。描述含有界参数和输出限制，不能携带秘密。
[实施契约与文件所有权](PERSONAL_TOOL_IMPLEMENTATION_CONTRACT.md)列出各模块接口。

工具输入采用 Draft 2020-12 JSON Schema，不受应用表单 schema 的较小词汇表限制。
根输入必须是 object；schema 规范化后的 JSON 上限为 32,768 字节，调用参数为 64 KiB，
并沿用深度、节点数、容器及字符串大小限制。`fc`、`run_context`、`_agno_run_context`
保留给框架，不能声明或传入为业务参数。验证不会联网读取外部 `$ref`；需要外部解析的
参数校验失败，不自动获取依赖。描述和 schema 在登记时快照，后续变化不能沿用旧 pin。

Settings 将这些描述接入现有静态 runtime adapter 和 tool policy 注册；新增工具不需要修改
agent loop、队列或应用注册表。核心与研究部署入口均使用同一注册。没有插件市场、动态
发现、自动安装、默认服务账号或新 RBAC。

## 连接 API

以下接口均采用现有身份、CSRF 和 `X-Factory-Expected-Owner` 约束，返回无秘密的元数据：

| 方法与路径（`/api/factory` 下） | 用途 |
| --- | --- |
| `GET /personal-tools/descriptors` | 列出静态工具描述和准确凭据用途/目标。 |
| `GET /personal-tools` | 仅列出本人登记及当前可用状态。 |
| `POST /personal-tools` | 用 `{adapterId, credentialRef, credentialRevision, requestId}` 创建本人登记。 |
| `GET /personal-tools/requests/{requestId}` | 找回原配置/撤销命令的登记，不触发工具。 |
| `GET /personal-tools/{registrationRef}` | 查看本人登记。 |
| `POST /personal-tools/{registrationRef}/revoke` | 用 `{requestId}` 撤销登记。 |
| `POST /user-connections` | 沿用现有 API 将该登记绑定为应用可选连接。 |

工具登记的 `revision` 是该 owner 配置的不可变版本，`descriptorRevision` 是静态 adapter
版本；两者不能混用。凭据、连接和描述发生变化时旧 pin 失效。SecretLease 仅在调用时
经 owner/reference/revision/provider/destination 全量授权后短暂解析，不写入材料、计划、
回执、事件、提示词、日志或输出。

## 一次调用的生命周期

原生 Function 同步构造，实际 IO 在 async 调用中启动。原生 `fc.call_id` 与 run ID 构成
既有 effect 身份；只有首次 reserve 的 `new` 可以派发，`done` 在重新授权后返回原结果。
结果不明时保留原 UNKNOWN effect，并通过 Agno 原生 `StopAgentRun` 停止下一轮模型
继续请求新 call ID。它不能撤回同一批已经并发发出的调用，也不提供远端 exactly-once
保证。队列票据结束不等于原副作用已经完成或停止。

`failed` 与 `stopped` 是两个独立维度。`failed, stopped=True` 可完成失败回执；
`failed, stopped=False` 则保存 `{outcome: "failed", stopped: false}`，同时让 effect
继续保持 UNKNOWN 和容量占用，并以 `PERSONAL_TOOL_FAILED_CLEANUP_UNCONFIRMED`
触发原生停止。重启不会将它转换成 DONE；在额度已被占满时，新任务仍被拒绝。

`ToolInvocation` 提供可信 owner、连接版本、原 call ID、业务参数及原生 RunContext，
并提供 `check_authorized()` 和 `resolve_credential()`。适配器在派发前和执行观察过程中
重查；旧 handle 不能越过撤销、版本变化或任务取消。认证状态按一次调用创建；结束时
处理本次资源的关闭和清理。schema 与 binary 可共享，认证和可变调用状态不能跨 owner
共享；关闭结果与业务结果分别核对。

## CLI 的实际执行范围

[personal_cli.py](../platform/agent_factory/personal_cli.py) 与
[_personal_cli_process.py](../platform/agent_factory/_personal_cli_process.py) 使用 POSIX
进程组，当前真实进程验收在 Linux 上进行；不支持 Windows 主机执行此 CLI 适配器。
Windows 浏览器仍可管理服务端的工具连接，页面可用不代表 Windows CLI 已实现。

每次成功调用顺序启动三个进程：无凭据负探针、带本次凭据的身份/来源探针、业务命令。
探针必须由部署登记为只读，并校验实际账号和认证来源；任一前置失败都不发出业务命令。
三步共用本次执行期限，每次启动前核对 executable 内容与当前授权。业务输入只映射到
登记的标量参数，使用 argv 数组，不接收用户 shell、命令路径或认证参数覆盖。

`CliCredentialDelivery` 明确选择 stdin、文件、环境变量或专用 HOME 内文件。每次调用
使用独立 HOME/config/cache/temp，子进程环境不继承宿主登录、代理或注入变量；不修改
服务全局环境。实际供应商是否尊重这些路径仍需独立验证。这些目录和同 UID 进程不构成
恶意代码沙箱，也不提供网络隔离。asyncio loop 开启 debug 时拒绝执行，以免底层管道
日志先于回显检查暴露秘密；适配器不会替调用方修改共享 loop 或全局日志配置。

业务是否派发与本地停止证据分开记录。只读探针停止未确认时，可以确认业务未发出而
返回 `failed`，同时保留 `stopped=False` 和私有目录。业务一旦派发，取消、超时、非零
退出或其他不明结果保留 UNKNOWN；即使本地进程组已停止，也不能推出远端副作用已撤销。
只有确认本地停止后才尝试删除私有目录，清理失败会报告固定错误，不能宣称全部清理。
停止证据仅覆盖本地进程组，不覆盖主动脱离该组的后代或远端操作。

## MCP 的实际执行范围

[personal_mcp.py](../platform/agent_factory/personal_mcp.py) 使用锁定的官方 `mcp==2.3.0`
`ClientSession` 与 Streamable HTTP client，不引入 FastMCP、stdio 启动或旧 SSE transport。
每次调用独占 client/session，初始化并核对登记的工具名及 schema 后，只派发一次
`tools/call`。不因交互式补输入要求、断线或 schema 变化自动再调用。

默认 endpoint 必须是 HTTPS。`allow_loopback_http=True` 只允许显式数字 loopback 地址
的本地测试服务器，不接受任意 HTTP 服务或 `localhost` 名称豁免。客户端不跟随重定向、
不读取宿主代理配置，关闭传输层重试且不重发业务调用；Bearer 凭据只向登记的准确 endpoint 发送，调用及
session DELETE 都重新检查当前 owner 和凭据版本。

`teardown_timeout_seconds`（默认 2 秒）为 session DELETE 提供一个总截止时间，覆盖
授权解析、响应头和持续分块的响应体，避免逐块活动延长关闭等待。它不证明服务器已经
删除会话或停止业务，也不能强制终止阻塞中的同步授权线程或任意自定义 transport。
关闭失败、调用结果未知和授权撤销均不能触发替代调用。

当前 MCP 失败路径默认未提供 `stopped=True` 的明确证明。经公共包装后，这类 `failed`
仍按未确认清理保留 UNKNOWN 和容量，不能仅凭失败响应宣称资源已释放；该保守行为不代表
已经实现远端停止证明。

已知凭据回显与超界输出拒绝进入模型及持久结果。异常只返回固定诊断码，不暴露子进程
stderr、远端响应或秘密。取消只有在正向停止证据成立时才记为 cancelled；关闭 MCP
transport 不证明远端操作停止。业务已派发后，无证明的取消、断线或丢回复保留原 UNKNOWN
effect；业务尚未派发的明确拒绝可以记为 failed，不能把它解读为资源已全部清理。

## 验证与限制

定向回归覆盖静态装配和标准工具 schema、双 owner 与同 owner 并发、凭据轮换/撤销、
原生身份及版本拒绝、无宿主账号 fallback、输出泄漏拒绝、停止证据、重复调用与 UNKNOWN
不重放。真实本地 CLI/MCP 还通过 Agno `FunctionCall.aexecute()` 与共享包装集成，使用
内存 effect 夹具核对成功回执重用时不再派发。真实 PostgreSQL/Agno 测试另沿声明式应用
调用惰性合成工具，核对原生停止、effect 重开、未确认停止持续占用容量及撤权后阻止下一调用。
Chromium 使用完全拦截的合成 API 检查桌面/窄屏绑定、丢回执恢复、
撤销及账号变化，不启动 CLI/MCP 或模型。[验证命令](DEVELOPMENT_CHECKS.md#personal-cli-and-mcp-verification)
区分各层证据；具体运行结果保留在对应 PR 中，不把用例数量当作固定验收目标。

供应商特有账号校验、复杂 OAuth/证书/cookie jar、跨主机 shell、远端操作停止证明、
强 OS 隔离和生产容量仍需对应目标的独立验证。本实现不暗示这些能力已经交付，也不
将合成凭据测试记作真实外部服务验收。
