## ADDED Requirements

### Requirement: Product has no demo authentication mode
产品 SHALL 只提供明确配置的身份认证；MUST NOT 暴露固定 persona、演示 cookie、内置 mock IdP 或可启用的 demo 配置。

#### Scenario: Obsolete mode or missing identity configuration
- **WHEN** 操作员使用旧 demo/mock 开关或未配置必要身份与签名参数启动
- **THEN** 产品明确拒绝配置或登录，不创建 demo 账号、临时签名密钥或替代会话，不在失败前写入演示数据

#### Scenario: Configured OIDC browser identity
- **WHEN** 已配置 OIDC 身份登录、回跳、刷新、退出和重新登录
- **THEN** 复用真实会话/CSRF/安全重定向与成员权限，OIDC 验证失败不自动切换身份；另行显式配置的本地密码入口独立验证

#### Scenario: Internal signature cannot replace configured authentication
- **WHEN** 客户端直接向公开入口提交为既有成员签发的合法内部 JWT、旧 demo cookie 或 WebSocket 身份帧
- **THEN** 公开应用拒绝认证；健康/静态与原有受信任 in-process native 执行路径保持独立

### Requirement: Synthetic fixtures are not deployable product modes
合成身份/材料/模型 SHALL 仅在测试边界显式提供，MUST NOT 随产品 wheel、正式前端或部署入口提供可启用旁路。

#### Scenario: Installed core and build inspection
- **WHEN** 独立安装 core wheel 或运行正式前端/部署
- **THEN** 不包含可运行演示身份服务、种子回退、原型入口或单 HTML 演示产物

#### Scenario: Deterministic acceptance
- **WHEN** 测试在隔离数据库使用合成成员/本地 OIDC/模型
- **THEN** fixture 来源在 tests，产品正常认证与权限断言仍执行，结果明确不是实际外部 IdP 验收

### Requirement: Existing data is retained without promotion
升级 SHALL 保留原数据库/用户/凭据/产物，不自动清空，也不把旧 demo 账号提升为生产身份。

#### Scenario: Existing demo database
- **WHEN** 新产品遇到旧 demo 状态
- **THEN** 拒绝隐式模式转换，说明准确限制；只读盘点和后续单独确认才可执行数据清理
