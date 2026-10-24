# Proposal

## Why

成员创建的 CLI/MCP 资源每次分配新 adapter，导致 Bob 无法以自己的账号连接执行 Alice 发布的同一材料。需要将可公开复用的操作与私有账号连接分开，同时保留原生调用的精确身份和原操作恢复。

## What Changes

- 成员显式创建不可变公开操作，完整 dispatch recipe 参与 hash；不自动发布已有私有配置。
- 独立账号资源引用同一操作版本，在进程内使用同一个 adapter 实例；保留精确 connection adapter 和对象身份校验。
- 恢复时先恢复操作，再恢复账号；账号撤销独立，材料撤销仍即时阻止后续调用。
- 提供创建操作、为操作连接账号和选择个人/共享连接的最小 API/UI，补真实 native CLI/MCP、双用户、PG 与重启验收。

## Capabilities

### New Capabilities

- `reusable-member-tool-operations`: 成员公开操作的不可变身份、独立账号绑定及恢复连续性。

### Modified Capabilities

无；当前主规格目录没有同类 capability。

## Impact

基线：planning `84c827c` + main `9a933aa`。范围为 core personal_tools、原生 personal_tool_execution、材料/连接入口和资源 UI；不依赖 #97/#99；后续因可复现授权读取开销明确叠加 #103 c2033e6。旧 installed adapter、member resource、plan/effect 保持原语义与身份。不新增 OAuth 框架或运行引擎。生产实现及定向 native/browser 验收已完成，OS 正常进程替换已通过（非崩溃恢复）；未验证边界见计划证据。
