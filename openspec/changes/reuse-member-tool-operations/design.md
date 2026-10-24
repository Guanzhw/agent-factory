# Design

## Context

基线为 planning `84c827c` 合并 main `9a933aa`；实现尚未开始。`configure_resource` 每次创建 `member-tool-*`，`ensure_registered` 从账号行恢复 adapter；`connection_adapter_ref` 要求精确 adapterId，原生 `personal_tool_registration` 同时要求 handle 与 registry 持有同一个 adapter 对象。保留这两个检查。现有 descriptor hash 不覆盖完整执行配方，不能作为操作等价证明。动机见 proposal.md。

## Goals / Non-Goals

**Goals:** 一个固定目标的公开操作版本对应一个进程内 adapter，多个独立账号引用它；原材料及原调用持续可核对。

**Non-Goals:** 不做不同目标/协议的自动兼容，不自动迁移私有配置，不新增 OAuth、通用连接框架、队列或运行引擎；不依赖 #97/#99，不改变旧效果身份。

## Decisions

### 操作与账号分开持久化

在现有 SQLAlchemy metadata 增加操作表：operation_id、version、owner_id、canonical body、operation_hash、created_at；唯一键 (operation_id, version)，已写 body/hash 不可更新。body 包含完整 descriptor 语义及规范化 recipe（排除自引用 hash、生成 ID、时间戳和账号字段）。MCP 包括规范化 URL 与 remoteToolName；CLI 包括 executable、arguments、argumentOptions、stdinJson、workingDirectory、environment、credentialEnvironmentVariable、outputFormat；schema、readOnly、timeout/maxOutput、权限和 credential provider/destination 亦进入 hash。未知字段拒绝，数组顺序保留。修改必须新版本并产生独立 adapterId/revision，不按工具名或 descriptor 猜测等价。

账号仍使用现有 owner tool 表、vault 和共享机制，新增 operationRef={id,version,hash}，body.adapterId 固定为该版本的 operation adapterId。每个账号保留独立 registrationRef/revision 和 credentialRef/revision；无账号覆盖配方入口。材料仍使用现有 MaterialDefinition/hash 与发布流程，其 runtime binding 固定该 operation adapter 和操作 hash。操作 hash 不等于材料 hash；现有材料可用性检查继续逐调用生效，不以操作表存在替代。

### 最小 API 与 UI

在现有 `/api/factory/personal-tools` router 增加 `POST /operations`（requestId + 明确提交的公开配方）、`GET /operations` 与精确版本读取，返回 operationRef、descriptor/runtimeBinding，供现有材料创建/发布入口使用；创建操作本身不暗中发布材料。增加 `POST /operations/{id}/accounts`（version/hash、requestId、credentialRef/revision 可选成对）创建独立账号。复用现有账号列表、共享、撤销和请求幂等服务；不同 payload 重用 requestId 冲突。

在资源页面提供“创建可复用操作”和“为此操作连接账号”，展示完整将公开的目标/配方。表单不自动复制旧资源；明确说明参数与环境变量会公开，秘密通过账号凭据注入，禁止认证信息嵌入 URL，避免将 vault 内容带进配方。任意字符串是否敏感无法自动可靠判断，成员须显式提交可公开内容；不声称扫描能证明无秘密。任务仍选现有个人/共享 connectionRef，显示 actor 与凭据所有者差异。旧资源入口保留。

### 恢复与撤销

服务初始化或延迟注册在既有 adapter lock 内，先读取验证操作 hash、构建一个 adapter 并注册，再恢复引用它的账号 handle。不同账号不能各自重建或替换该 adapter；不扫描首个 ACTIVE 账号作为操作事实来源。缺失/篡改操作或不可用 CLI 路径明确 unavailable，不回退其他账号或旧 adapter。

账号 revoke 仅修改账号行，不能删公共 adapter 或撤销其他账号。材料 withdraw 通过已有新鲜 material guard 阻止后续 dispatch；仍保留定义以核对历史。旧 resource 行继续按原逻辑恢复，旧 descriptor/effect fingerprint 不变。新操作的 runtime config/原生效果指纹纳入 operationHash，且仅影响新路径；继续使用原 native run/call identity 和 UNKNOWN no-replay。

## Risks / Trade-offs

- [公开参数可能被成员填入秘密] → 独立显式创建、公开预览、凭据字段拒绝、URL 认证信息拒绝和合成泄露测试；不自动发布私有资源。
- [恢复两账号创建两个 adapter] → 操作先注册、锁内复用同一对象，用真实 native 调用证明对象身份检查未被绕过。
- [撤销按 adapterId 批量伤及其他账号] → owner/reference 粒度更新与双用户撤销回归。
- [只测 resolver 掩盖 native factory 拒绝或重复派发] → disposable PG + 实际 CLI 子进程/loopback MCP + native AgentOS，多步、child、重启和丢失确认计数。

## Migration Plan

仅新增表/字段及 API，保留旧数据，不批量改写材料、账号、plan 或 effects。先交付操作/账号/恢复与单元验证，再接 UI 与端到端验收。回退旧版本会使新操作不可用；须保留新数据和原 UNKNOWN 记录，不能自动转换成旧私有资源或重派发。生产部署不在本次授权范围。
