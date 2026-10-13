# 个人连接驱动的 CLI / MCP 调用

PR #88 基于已合入的 `main@3ef542ba` 实现本能力。工具、schema 和依赖由部署静态安装；
应用声明工具及连接需求，成员保存本人凭据并绑定一次，后续调用沿原任务中的 owner 与
连接版本自动解析。普通绑定与调用不新增管理员逐次审批。

当前范围是通用接口及使用合成认证的本地 CLI 进程、MCP 测试服务器验证。具体外部供应商
尚未指定，不能据此声称已兼容某个商业 CLI/MCP 服务、其账号探测或 OAuth 刷新。
不运行 AutoResearch 任务或真实模型，不改变生产身份、管理员权限及网络安全设置。

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
既有 effect 身份；只有首次 reserve 的 `new` 可以派发，`done` 返回原结果，`unknown`
只保留未决状态。没有自动重试或 exactly-once 的远端保证。

`ToolInvocation` 提供可信 owner、连接版本、原 call ID、业务参数及原生 RunContext，
并提供 `check_authorized()` 和 `resolve_credential()`。适配器在派发前和执行观察过程中
重查；旧 handle 不能越过撤销、版本变化或任务取消。认证 session 初版按一次调用创建并
在 finally 关闭；schema 与 binary 可共享，认证和可变调用状态不能跨 owner 共享。

CLI 使用 argv 数组及本次进程专用的凭据输入/HOME/config，不改服务全局环境。具体
stdin、文件或环境策略由该 adapter 明确选择；不能假设所有供应商 CLI 都尊重 HOME。
临时目录只防止意外串用，不构成同 UID 恶意程序的 OS 隔离。

已知凭据回显与超界输出拒绝进入模型及持久结果。异常只返回固定诊断码，不暴露子进程
stderr、远端响应或秘密。取消只有在正向停止证据成立时才记为 cancelled；关闭 MCP
transport 不证明远端操作停止。无证明的取消、断线或丢回复均保留原 UNKNOWN 回执。

## 验证与限制

定向回归覆盖静态装配和 schema、双 owner 与同 owner 并发、凭据轮换/撤销、原生身份
及版本拒绝、无宿主账号 fallback、输出泄漏拒绝、取消清理、重复调用与 UNKNOWN 不重放。
本轮先运行本地合成协议/真实进程测试及日常 fast CI；精确结果见 PR 验证记录。

供应商特有账号校验、复杂 OAuth/证书/cookie jar、跨主机 shell、远端操作停止证明、
强 OS 隔离和生产容量仍需对应目标的独立验证。本实现不暗示这些能力已经交付，也不
将合成凭据测试记作真实外部服务验收。
