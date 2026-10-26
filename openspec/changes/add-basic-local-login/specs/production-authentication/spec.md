## Purpose

让少量由操作方显式创建的普通成员使用真实用户名密码验证当前功能，继续复用正式会话、退出和用户资源隔离；本地登录与现有 OIDC 独立选择，不引入默认身份、公开注册或账号管理系统。

## ADDED Requirements

### Requirement: Local accounts require explicit operator creation
产品 SHALL 只允许受控本机命令创建新的本地普通成员，使用成熟库加盐密码 hash；MUST NOT 默认创建账号、静默绑定既有 owner、公开注册或暴露密码/hash。

#### Scenario: New account and collision
- **WHEN** 操作方交互输入有效用户名密码创建账号，或目标 native owner/本地凭据已存在
- **THEN** 新账号持久化为普通成员且只保存 hash；已有目标明确拒绝，原身份、权限及凭据不变；失败/中断不产生可登录的半成品凭据

### Requirement: Local password login uses the existing browser session
产品 SHALL 在显式配置本地登录后验证用户名密码与当前成员状态，并复用可撤销持久会话、HTTPS cookie、Origin/CSRF、native user_id 与退出；MUST NOT 以本地失败回退 OIDC 或接受公开内部 JWT。

#### Scenario: Success and failure
- **WHEN** 浏览器提交正确密码，或提交错误密码、未知用户、禁用用户及跨 origin 请求
- **THEN** 仅合法当前成员获得绑定其原身份的会话；其余拒绝且不新建会话；响应/日志/浏览器持久存储均无密码/hash

#### Scenario: Logout restart and owner isolation
- **WHEN** 两用户分别登录、服务重启、退出后重用旧 cookie，或登录成员随后被禁用
- **THEN** 未到期合法会话跨重启保留同一 owner；退出/禁用阻止后续受保护读取；一人的会话、资源、凭据与任务不能成为另一人的权限，缺失/错误 CSRF 仍拒绝写入

#### Scenario: Explicit login methods
- **WHEN** 仅配置本地登录、仅配置 OIDC、两者均配置或均未配置
- **THEN** 页面只提供已配置入口，OIDC 原契约保持；未配置时明确无法登录，旧 demo 开关、mock IdP、默认账号和内部 JWT 旁路仍不可用

### Requirement: Login reaches the configured application workspace
产品 SHALL 让合法本地成员进入正式工作台，并只显示所选部署已装配的应用；登录功能 MUST NOT 注入研究数据、合成身份接口或模型配置。

#### Scenario: Formal core and Research builds
- **WHEN** 隔离 PostgreSQL 中由真实本机命令创建两账号，分别通过正式 core 和显式 Research build 的真实 HTTPS 页面登录
- **THEN** core 主页为空应用目录；Research 主页可进入空研究工作台并返回、刷新与退出；上述验收不调用模型、不证明实际研究或企业 IdP 可用
