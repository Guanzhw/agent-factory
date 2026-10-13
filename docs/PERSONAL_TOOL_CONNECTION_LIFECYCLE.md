# 个人连接驱动的 CLI / MCP 调用（提案）

**状态：documentation only；低优先级；depends on [PR #86](https://github.com/Guanzhw/agent-factory/pull/86)。**
本 PR 只记录设计和后续任务；须待 #86 验收并合入 main 后再实施。文档基于
`main@615a23f`，下方源码参考使用尚未合入 main 的 #86 快照 `8b96664`。
现有接口不等于这项能力已经完成；本次不实现功能、不使用真实密钥、不部署。

## 用户旅程与范围

平台为部门内小几十名成员托管应用 agent。共享安装的 binary、依赖和工具 schema；
每个人绑定自己的账号，agent 按需使用该连接，不因认证而逐用户或逐任务创建容器、
虚拟环境或常驻工具服务。普通绑定与调用不新增管理员逐次审批。

1. 用户在应用中选择所需工具，绑定本人已保存的连接或通过现有安全入口新增凭据。
2. 适配器检查实际凭据读取来源与上游账号，展示脱敏账号标识；不确定时拒绝绑定使用。
3. 用户使用 agent；模型只提供业务参数，后端从可信任务绑定选择 owner、连接与版本。
4. 用户更换或撤销连接后，旧绑定拒绝后续调用；历史记录保留，未知请求按原回执核对。

先选择一个真实 CLI 和一个需要个人认证的 MCP 服务。具体工具尚未选定，`codehub`
只是接入形式的例子。此任务不增加工具市场、新 RBAC、审批系统或计费/配额产品。
原有危险操作确认、TLS/SSRF、任务边界和实际停止证明继续适用。

## 职责与已有基础

| 层 | 负责什么 |
| --- | --- |
| Core | 复用 RunContext、ExecutionBindings、ConnectionService、vault 和 effect 回执；补连接检查、按需打开、调用、核对、取消及关闭的公共生命周期。不得依赖 research。 |
| 应用 | 声明工具/连接需求，提供绑定账号的入口与业务结果展示。应用定义、skill、提示词和模型参数不持有秘密，也不自行解析 vault。 |
| 独立 adapter | 工具业务参数、认证格式、CLI argv/输出解析、MCP transport、账号探测及刷新语义。工具特例留在适配器，不成为 core 的应用分支。 |
| 部署组合入口 | 静态安装和注册选定工具/适配器与已有目标策略；复用现有并发和运行限制，不新增授权中心。 |

以下引用均指向 **#86 的新 layout，尚非 main 已交付状态**：

| 已有接口 | 可复用部分与边界 |
| --- | --- |
| [runtime.py](https://github.com/Guanzhw/agent-factory/blob/8b9666449e11262356b543f5a72d1fb2b8042232/platform/agent_factory/runtime.py)、[execution_bindings.py](https://github.com/Guanzhw/agent-factory/blob/8b9666449e11262356b543f5a72d1fb2b8042232/platform/agent_factory/execution_bindings.py) | 原生 RunContext、BindingContext.connection、注册与调用前重查。factory 目前必须同步返回；tools_for 只接受匹配名称的 Function/callable，不能直接塞入 MCPTools toolkit。异步工具函数不等于已有异步连接生命周期。 |
| [connections.py](https://github.com/Guanzhw/agent-factory/blob/8b9666449e11262356b543f5a72d1fb2b8042232/platform/agent_factory/connections.py) | tool 类型连接、owner/版本/能力检查与不透明 handle；尚无可直接使用的通用 CLI handle。 |
| [credential_vault.py](https://github.com/Guanzhw/agent-factory/blob/8b9666449e11262356b543f5a72d1fb2b8042232/platform/agent_factory/credential_vault.py)、[personal_remote_provider.py](https://github.com/Guanzhw/agent-factory/blob/8b9666449e11262356b543f5a72d1fb2b8042232/platform/agent_factory/personal_remote_provider.py) | 按 owner、用途、目标、引用和版本解析短暂 SecretLease；当前用户名/密码或 token 形态有长度与字符限制，不是任意 blob、证书、cookie jar 或 OAuth 状态仓库。 |
| [store.py](https://github.com/Guanzhw/agent-factory/blob/8b9666449e11262356b543f5a72d1fb2b8042232/platform/agent_factory/store.py)、[workflow_operations.py](https://github.com/Guanzhw/agent-factory/blob/8b9666449e11262356b543f5a72d1fb2b8042232/platform/agent_factory/workflow_operations.py) | 复用现有 effect 身份、持久回执与原操作核对；适配器仍须证明目标工具的副作用与停止语义，不能把本地回执当作远端 exactly-once 保证。 |

Agno 已提供 MCPTools，可按需薄适配其客户端及 async connect/close；所需可选依赖和
生命周期接线仍待补齐，不重写 agent loop。
[research/tools.py](https://github.com/Guanzhw/agent-factory/blob/8b9666449e11262356b543f5a72d1fb2b8042232/apps/research/agent_factory_research/tools.py)
是研究应用的合成执行实现，不是通用工具层。通用 CLI executor/handle、MCP client 接入与
异步生命周期、应用内个人工具连接 UI 接线都仍待实现。

## 最小接口草案（proposal，非现有 API）

```python
handle = bind_tool(binding_context)  # 可信后端注册入口；只绑定非秘密引用
result = await handle.invoke(business_args, operation_id=original_effect_id)
await handle.reconcile(original_effect_id)  # 只核对原调用
await handle.cancel(original_effect_id)     # 请求停止，不宣称已经停止
await handle.aclose()
```

名字和签名待首个适配器验证后确定。同步 factory 可返回惰性 handle，实际连接在 async
调用内建立并由生命周期钩子收尾。调用前重新核对当前 owner、原生 run、连接/凭据版本、
目标及授权；模型提供的 owner、连接路径或任务 ID 不构成授权。应用只消费业务接口，
BindingContext 与 SecretLease 留在可信后端。CLI 与 MCP 共用这些边界及既有调用回执，
不另建调度器或一套任务状态机。

## 共享内容与私有状态

| 内容 | 默认处理 |
| --- | --- |
| Binary、依赖、已注册 adapter、公共工具 schema | 共享只读定义；认证对象、结果和用户数据不放入全局共享实例。 |
| CLI 无状态调用 | 优先 stdin 或显式 credential path；使用 argv 数组，不拼接任意 shell。临时文件位于受控目录、限制权限且不进入 agent 工作区；秘密值不进入命令参数、日志、模型上下文或产物。 |
| 旧 CLI 的 HOME/config | 只设置本次子进程的环境和专用目录，不修改服务进程全局环境。默认用临时状态；仅工具确需 refresh/cache 时保留 owner + connection 的私有状态，并区分有效版本。 |
| 同连接改写 | 仅在 refresh/config/cache 改写需要时按 owner + connection 串行；不同连接继续并发，不用全局锁。轮换不得让旧状态重新覆盖新版本。 |
| MCP | 共享定义；认证与 session 按 owner + connection + revision 隔开，revision 包含连接和凭据版本。无状态 transport 每请求注入本人认证；有状态 transport 按需连接、空闲关闭，不能跨 owner 复用认证 session。 |

不能假设工具尊重 HOME：可能读取绝对路径、OS keychain、其他配置目录或环境凭据。
默认路径必须在真实工具上确认读取来源及上游账号，显式排除服务账号/宿主缓存等隐式认证；
缺少本人凭据、来源不明或账号不符时失败，绝不 fallback 服务账号。
硬编码认证绝对路径或任意 shell 需要独立评估的具体例外，不扩展默认方案。
更换目录仅防止串用；同 UID 的任意进程之间不构成强隔离。新增系统账号、OS/网络安全
变更不在本次文档授权内，不能据此宣称恶意同 UID shell 隔离已完成。

简单 token/用户名密码可由 adapter 用现有 SecretLease 生成工具格式；复杂认证状态仅在
真实工具需要时增加专用类型。token refresh 的本地缓存不默认回写或覆盖 vault；如需回写，
须另定本人连接、精确版本 CAS、冲突与撤销语义，沿用现有轮换流程。

## PR #86 之后的实施顺序

1. **前置条件：** #86 验收合入 main；按届时 layout 复核引用，选定真实 CLI、个人认证 MCP
   和获准测试账号，记录凭据来源、账号探测、取消及副作用契约。
2. **先做最小纵向验收：** 用现有绑定/vault 与薄适配器接通两个工具及最小应用绑定入口，
   完成下表双用户真实并发验收，再决定公共生命周期需要补什么；不先建设通用网关。
3. **收敛公共能力：** 将已验证的连接/调用生命周期放入 core，具体格式和业务契约留在
   adapter；补齐当前身份重查、轮换、清理与原回执核对，再扩展更多工具。
4. **必要后续入口：** 只有实际 skill/shell 使用需要时再提供 `af-tool` 薄客户端，复用同一
   可信执行上下文与调用路径；普通任务 ID 不是认证。跨主机接入另行验证，不预造认证网关。

## 验收与当前限制

| 验收 | 必须观察到的结果 |
| --- | --- |
| 两用户、同用户并发 | 同一真实 binary 和个人认证 MCP 服务分别返回正确账号与结果；同用户多调用/多连接不覆盖参数、临时状态或 session；仅同连接必要改写串行。 |
| 实际认证来源 / 无 fallback | 验证默认查找路径、环境变量与缓存；缺少本人认证或故意放置错误宿主账号时拒绝，不能悄悄使用服务账号。 |
| 轮换、撤销、无泄露 | 旧连接、旧凭据版本和已缓存 handle/session 的后续调用被拒绝；重建时重新核对账号。其他 owner 不可读秘密；stdout/stderr、错误、事件、提示词和产物无秘密。 |
| 身份、幂等、UNKNOWN | 伪造绑定被拒绝；相同原请求只保留原 effect。丢回执、重启及上游结果不明时保留 UNKNOWN，核对原身份，不换 ID 重派副作用。 |
| 取消、清理与停止证明 | 取消只请求停止原调用；验证原 CLI 进程/子进程退出后清理临时凭据，重启回收残留。关闭 MCP transport 不证明远端操作停止；无上游停止证据则保留未决记录，不释放未确认的远端资源。空闲 session 最终关闭。 |
| 开销与复用 | 无逐用户常驻服务或逐任务认证容器；记录实际耗时、峰值 RSS 和空闲资源回收，不用规划值冒充实测容量。 |

合成测试先覆盖并发、拒绝、轮换和故障路径；真实 CLI 与个人认证 MCP 的上述双用户验收
是后续实现完成的必要条件，分别记录工具版本和证据。当前未选工具，未执行这些验收，
也未验证复杂 OAuth/证书、远端 shell/跨主机兼容或强 OS 隔离。本提案不扩大现有真实
proxy/key/账号授权，不授权真实模型请求或部署。
