# Tasks

## 1. 先审方案

- [x] 1.1 非作者核对精确 base/spec、最小范围与身份/会话边界，记录方案 PASS 后实施。

## 2. 最小登录实现

- [x] 2.1 增加受控新成员 CLI、私有加盐 hash 存储及 root/core 依赖；验证随机盐/非明文、用户名冲突拒绝、并发创建不覆盖、hash 写入前失败不具备本地登录能力，不输出密码/hash。
- [x] 2.2 最小解耦现有 session 与 OIDC，增加本地登录配置/端点；便携与真实 PostgreSQL 验证成功/失败无新 session、退出旧 cookie 失效、禁用、双 owner 隔离及重启，保留 OIDC/HTTPS/Origin/CSRF/内部 JWT 回归；核心新 selectors 加入现有 fast 分组。
- [x] 2.3 原登录页增加表单并保留 OIDC，运行相关前端测试；README 放唯一完整本机账号/HTTPS/登录步骤，DEVELOPMENT_LOGIN、REMOVE_DEMO_UPGRADE、SECURITY、DEPLOYMENT_VALIDATION、TEAM_MEMBERSHIP 仅简短对齐，.env.example 与 IMPLEMENTATION_CLOSURE_MAP 同步短声明，不改验收 schema 或历史证据。

## 3. 集成与复审

- [x] 3.1 用真实 CLI 创建隔离两账号，实际 PostgreSQL 和正式 core/Research build 运行 HTTPS 浏览器成功/失败/退出、主页与 Research 入口/空工作台/返回/刷新；不注入 session、mock IdP 或模型，不记录密码/hash/cookie。
- [ ] 3.2 执行 npm check/依赖 audit、Python ruff/pyright/architecture、相关包装检查与 OpenSpec strict；记录首失败/未验事实，非作者审精确完整 diff/简洁性并整改，由协调者核验精确发布 head CI。
