# Design

## Context

基线与目标见 [proposal.md](proposal.md)。`browser_auth.py` 已有持久 opaque session、注销、Origin/CSRF 和 native token 桥，但 origin/fingerprint 来自必填 OIDC 配置；`main.py:395` 仅在 OIDC 配置存在时装配。`App.tsx` 将 enabled 等同企业登录。native 用户目录不存密码，现有账号 API 保持原样；Research 有独立部署/前端入口。

## Goals / Non-Goals

**Goals:** 少量显式账号经真实密码验证进入原工作台，保留 native owner 和资源隔离。

**Non-Goals:** 不做首管理员、公开注册、成员管理改造、改密/恢复、身份自动合并、认证策略层或未来公司登录适配框架；不改 Research 业务与既有数据。

## Decisions

1. **受控创建。** 新增 `agent-factory-local-user USERNAME`（root/core wheel 均安装），只供操作方停服务时创建普通成员。复用现有账号 ID 规则、native UserDirectory API；密码由交互式 `getpass` 输入并确认，不接受密码 argv/env，不回显或输出 hash。持有 PostgreSQL 创建锁检查 native owner 与本地凭据均不存在；任何冲突都拒绝，不绑定旧 OIDC/demo 身份，不授管理员角色。只用现有数据库配置，不启动应用/队列。停服务是运行说明，不增加服务协调机制。
2. **密码存储。** root/core 显式锁定 `argon2-cffi==25.1.0`，使用其 [PasswordHasher](https://argon2-cffi.readthedocs.io/en/stable/api.html) 默认 Argon2id/随机盐及标准编码；单独私有 `af_local_passwords(owner,password_hash)` 表，不放 native metadata、vault、API 投影或日志。用户名精确匹配；密码支持 12–128 个字符，不裁剪/截断；不自制 hash/pepper。native API 自行提交：创建成员后才写 hash，两者齐全才可登录；失败非零、中断结果未知不得报成功，不覆盖、删除旧用户或自动补绑；此命令不含重置/恢复流程。
3. **复用会话。** `Settings.local_login_origin` / `FACTORY_LOCAL_LOGIN_ORIGIN` 显式启用且必须为 HTTPS origin；未配置不开放本地登录。仅从现有 BrowserSessionService 的 OIDC 参数解耦 origin/会话启用；不新增会话类。与 OIDC 同时配置时 origin 必须一致，OIDC 参数仍只控制既有 `/auth/login`/callback。会话 fingerprint 保留配置变化失效语义；本地登录不要求 IdP，但仍用现有持久表、15 分钟到期、Secure/HttpOnly/SameSite cookie、Origin/CSRF 与短效内部 native token，公开入口仍拒绝直接内部 JWT。
4. **小登录面。** 新 `/api/factory/auth/local-login` 仅收有界用户名密码 JSON，强制配置 origin/HTTPS；验证 hash 和当前成员后在现有会话事务内再次检查 disabled，再创建会话、撤销同浏览器旧会话/未完成 flow。失败统一返回认证失败，不创建 session、不回传密码或 hash；数据库不可用明确失败。`/auth/config` 分别声明 local/OIDC 可用性，两个入口不互相回退。前端在原登录页加表单，密码仅短暂在组件内存，提交后清空；成功调用现有 session API，退出沿用现有注销，不改账号管理页面。

## Risks / Trade-offs

- native 用户与 hash 无共用事务 → 本机创建锁防止两个命令抢同名，成功前检查两者齐全；中断可能留下无本地凭据的普通成员，明确报错而不自动接管或清理。测试覆盖冲突/中断不获得登录能力。
- 会话与 OIDC 解耦可能削弱原边界 → 保留既有 OIDC/Origin/CSRF/注销回归；两用户、禁用与重启用实际 PostgreSQL 验证。无 HTTP loopback 特例、测试身份路由或数据库会话注入。
- “登录成功”不等于应用验收 → 正式 core build 验证主页/空目录；显式 Research build 验证主页→AutoResearch 空工作台→返回。不得创建研究工作、调用模型或宣称真实 IdP/GPU 验收。

## Migration Plan

方案先独立审查。实现只加凭据表/库依赖和上述入口；旧账户/会话、OIDC 及数据保留，禁用本地配置即可关闭本地入口。更新必要登录说明及旧 external-only 场景；验收只存简短结果和精确 base/head，密码/hash/完整浏览器存储不入证据。将核心 local-login 契约与 PG selectors 加入既有 fast 分组，不更改 CI 门槛；非作者完整 diff/简洁性复审后由协调者核验发布 CI。

## CI diagnostic follow-up

基线 `c50c2278826a5407c403ab046952b3f98a5385a2`。Full `40351648714` 的既有 MCP late-teardown 用例只记录 entered 等待超时，清理吞掉 pending 结果；相关产品与测试均未被本 PR 改动。受控探针证明原 DELETE 期限可在 resolver 进入前到期并正确保留 UNKNOWN，但历史 CI 是否此路径仍未知。

仅调整该测试：在原 2 秒内同时等待 entered/pending，以 entered 实际状态优先；未进入而 pending 已结束则传播原固定错误，正常返回或未就绪仍失败，超时只给布尔/计数诊断。保留原 0.1 秒 DELETE 总期限、全部 late/UNKNOWN/不重试/无 DELETE 断言和清理；新增 waiter 在原有界 gather 内回收，不预热或接受未进入为通过。先独立审计划；受控探针须从旧版等待超时变为新版明确早结束错误且仍红，正常三种 late 情形各执行一次。此为诊断改进，最终 CI 若通过也不宣称已定位历史根因。
