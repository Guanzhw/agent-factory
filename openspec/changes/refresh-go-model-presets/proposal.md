# Proposal

## Why

Go 快捷配置仍填入旧基础地址与 `deepseek-flash`，快捷预设与当前官方模型和端点表不一致。基线为 `db6d62a4880466f3bf50879809e2339e57cf8a44`；本次恢复丢失的未推送方案，不重写历史验证记录。

## What Changes

- 两个 Go 预设统一使用 `https://opencode.ai/inference/go/openai/v1`；DeepSeek 改为 `deepseek-v4.1-flash`，显示名注明 V4.1，保留原 preset ID。
- GPT 6 Luna 保持 `gpt-6-luna` 与 Responses；DeepSeek 保持 Chat Completions。
- 旧 saved 配置及 pending 原请求不自动迁移；保留 Longcat 历史 thinking 条件，删除无消费者的 `GO_BASES`。

## Capabilities

### New Capabilities

- `owner-model-presets`：模型快捷配置显式填写官方模型、协议和端点，保留已有配置与原请求身份。

### Modified Capabilities

无；当前主规范目录没有模型预设规范。

## Impact

仅修改 `web/modelProviderConfig.ts`、`tests/owner-model-settings.test.ts` 和本变更短说明。以 UI 保存 payload 的独立期望验证两个预设，以及旧配置输出调整和 pending 恢复不迁移；运行 `npm run check`、生产及完整依赖 audit。有现成浏览器工具才补充浏览器验证。只读核验 [Go 官方端点文档](https://opencode.ai/v2/docs/console/go/#endpoints)，不读密钥、不发真实模型请求、不改依赖、后端、旧验收脚本、所有权或权限，不推送或发布。
