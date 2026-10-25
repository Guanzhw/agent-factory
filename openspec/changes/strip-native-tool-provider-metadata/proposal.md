## Why
Agno 原生等待工具序列化包含本地 external_execution 布尔字段，OwnerChatModel 原样传入严格 provider codec 导致合法等待请求在 HTTP 前失败。

## What Changes
在 SDK 到 provider 边界仅复制移除已识别布尔元数据，不改变原工具、原生等待或 codec 未知字段拒绝。

## Capabilities
### New Capabilities
- `native-tool-provider-boundary`: 本地执行元数据与供应商工具声明分离。

## Impact
仅 byok_model、专属便携测试；无 schema、应用或原生生命周期改动。基线 1ed1d72。
