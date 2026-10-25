# Proposal

## Why
用户明确要求不保留任何 demo 模式。当前默认 Settings、启动脚本、固定 persona 登录、内置 mock OIDC 和单 HTML 原型让未经真实身份认证的路径可作为产品启动，必须移除。

## What Changes
- **BREAKING**：删除产品可启用的 demo/development mock 登录、合成种子和演示回退；旧开关明确拒绝，不能静默转换为可登录服务。
- 正式浏览器沿用已实现 OIDC 会话/安全回跳；未配置身份时 fail closed，不自动生成成员、身份服务或签名凭据。
- 内部合成测试迁至测试范围，不作为 wheel、正式构建或部署旁路。移除可运行原型交付，保留历史 Git/截图/失败记录。
- 保留所有既有数据库、账号、凭据和产物；旧 demo 数据只读盘点，绝不自动迁为生产成员或清空。

## Capabilities
### New Capabilities
- `production-authentication`：产品只接受明确配置的真实身份路径，测试身份不成为运行模式。
### Modified Capabilities
无已归档主规格。此变更覆盖历史 change 中允许产品 demo 的行为。

## Impact
platform 配置/认证/装配/合成注册与种子；deployment CLI；前端登录/原型；scripts 启动/打包；测试 fixture 与 CI、当前运维文档。基线 9454000e088ca6fba55621b8b2443ab55ffcc764。
