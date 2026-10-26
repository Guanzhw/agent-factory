# Proposal

## Why

当前没有企业 IdP 时无法通过正式页面登录验证功能。增加真实用户名密码登录，复用现有会话与用户隔离；后续内网应用可替换登录和用户管理，此次不建设账号管理系统。

## What Changes

- 一个受控本机命令显式创建少量新普通成员及加盐密码 hash；无默认账号、公开注册或既有身份自动绑定。
- 登录页增加用户名密码表单，复用持久会话、CSRF、native user_id 和退出；保留明确选择的 OIDC 入口。
- 只增加必要契约、真实 PostgreSQL/正式浏览器验收及运行说明；不新增首管理员、成员管理界面、改密、重置恢复、邮件、MFA 或认证插件层。

## Capabilities

### New Capabilities

- `production-authentication`：尚无归档主规范，沿用现有 capability 路径，补充显式本地认证；无 demo、内部 JWT 不可公开替代认证的边界保持。

### Modified Capabilities

无已归档主规范修改；既有移除 demo 场景仅澄清 OIDC 分支，不把外部 IdP 当所有登录的必需条件。

## Impact

基线 `768e4adcb0e218f9ec27b81e5627db1fb3f21034`。范围限 core 密码存储/命令、现有 browser_auth/config/main、登录表单、相关测试/fast selectors/说明，以及 root/core Python 依赖与锁文件；账号管理 API/UI、owner/vault/权限及 Research 业务不变。无需生产凭据、真实 IdP、模型或网络权限。
