# 个人凭据与连接

Factory 的「我的凭据与连接」（`?tab=connections`）统一显示当前用户的模型 API 密钥、服务令牌和登录凭据的用途、HTTPS 目标、状态与不透明引用。用户自行添加、更换和撤销；不提供明文密钥查看。模型配置仍可在「我的模型/API」一次保存密钥、模型与默认选择。OpenResearch 服务令牌与模型 API 密钥是不同用途，Factory 不把 BYOK 密钥转交给远程 OpenResearch harness。

本入口复用现有 `EncryptedCredentialVault`、个人模型和资源连接服务。没有另建 secrets 平台、通用秘密插件或应用内部凭据存储。尚未安装可信 vault 时，入口显示未启用，不创建默认加密密钥，也不从环境、个人文件或已有数据库寻找秘密。列表沿用现有接口的最多 100 条限制。

## 用户操作与失效语义

1. 添加：选择已部署的用途、精确 HTTPS 服务源及认证方式，填写新秘密并确认安全保存。保存不访问提供方，不创建授权、远程资源或模型调用。随后在模型设置或远程配置中绑定引用。
2. 更换：对当前引用与版本执行 compare-and-swap，得到新 `credentialRevision`。旧连接和旧任务绑定失效。模型设置提供「绑定更新后的凭据」，只提交非秘密元数据并生成新连接；远程服务使用原「重新配置→验证→绑定」流程。新版本不会自动写入旧计划、任务或应用配置。
3. 撤销：用户明确确认后，vault 清除该引用的密文与 nonce。提供方/目标策略退役后，原引用仍不能使用或轮换，但本人可按精确引用/版本撤销并清除密文。关联模型/连接的后续授权及秘密解析失败；任务上下文、原生 run、不可变计划、事件和已有结果保留。页面不自动重试任务，也不宣称已经停止上游正在处理的请求。
4. 确认未知：浏览器只保存当前用户、操作、原请求 ID 与非秘密用途/引用元数据；秘密输入立即清空。刷新后只读原回执，不重复发送秘密、轮换或撤销。

用户名和秘密仅存在于输入阶段与执行端的短暂 `SecretLease`；不会由 GET、回执或管理页面返回。切换账户的旧标签页在提交前核对当前 session，每个新增管理请求携带 `X-Factory-Expected-Owner`。服务端在同一请求里核对已验证身份，拒绝检查之后发生的账户切换竞态。

## 已有 HTTP 契约

这些路径沿用已有 vault 契约，没有新建公共 SDK 或更改应用 `contractVersion`。所有请求走现有同源登录/CSRF 边界，响应为 `private, no-store`。

| 操作 | 路径 | 请求字段 |
| --- | --- | --- |
| 能力 | `GET /api/factory/personal-credentials/capabilities` | 无；仅返回 enabled/providerIds |
| 本人列表 | `GET /api/factory/personal-credentials` | 无 |
| 添加 | `POST /api/factory/personal-credentials` | requestId, providerId, destination, username, password |
| 更换 | `POST /api/factory/personal-credentials/{credentialRef}/rotate` | requestId, credentialRevision, username, password |
| 撤销 | `POST /api/factory/personal-credentials/{credentialRef}/revoke` | requestId, credentialRevision |
| 恢复原回执 | `GET /api/factory/personal-credentials/requests/{requestId}` | 无；不重放操作 |

公共回执仅含 `credentialRef`, `credentialRevision`, `providerId`, `destination`, `status`。页面拒绝额外秘密字段、目标不匹配、错误版本及错误操作回执，不渲染原始错误正文。重复同一请求 ID/意图恢复原结果，不同意图拒绝；并发更换只有一个精确版本 CAS 成功。

## 应用接入与权限

应用按[公共版本化契约](APPLICATION_DEVELOPMENT.md)声明 `connectionRequirements` 的资源种类、能力和用途；用户在 Factory 绑定本人 `connectionRefs`。模型和远程配置只记录对应用途、目标及不可变凭据引用/版本。秘密不能进入应用 `config`、材料、提示词、模型上下文或浏览器存储；应用也不能取得 vault、`BindingContext` 或内部存储接口来自己解析秘密。

可信执行适配器在实际调用前通过现有连接授权重新核对用户、任务范围、能力、目标、版本和有效期，然后在执行端解析短暂秘密。过期、轮换、撤销、用户权限撤回均拒绝后续使用；读取历史任务和证据不需要重新取得执行秘密。已发出的外部请求无法靠本地撤销收回，停止仍走原 scoped cancellation 及证据机制。

正常个人资源使用不需要管理员逐次审批。管理员维护平台安装/允许的目标策略、用户访问、应用上线和可选共享资源；共享定义上线审核与普通用户个人凭据管理分开。管理页面没有查看用户明文秘密的功能。费用管理与平台模型收费保持默认关闭，用户自己的提供方费用不由 Factory 代收费。

## 本轮验证边界

- 浏览器/组件测试覆盖添加、更换、撤销确认、丢失回执后的刷新恢复、错误脱敏、禁用部署、两个标签页账户变化，以及模型显式绑定新凭据版本。
- `scripts/check_owner_byok_postgres.py` 必跑 15 个合成案例，零跳过要求；新增案例在独立 PostgreSQL 与实际 Agno 原生队列中完成 fake 模型任务后，验证更换/撤销拒绝后续使用，且原计划、任务上下文、事件和完成状态保留。
- 现有 vault 测试覆盖密文存储/重启、owner/provider/目标隔离、并发 CAS、回执恢复和撤销清除；现有连接测试覆盖验证过期与授权撤回。
- 只使用假凭据、内存 fake provider IO 和独立临时数据库。上述不证明真实模型/远程服务兼容、真实 OAuth 授权、科学结果、上游撤销传播或生产部署加密配置。
