# Tasks

## 1. Go 快捷配置

- [ ] 1.1 更新两项预设、保留 ID 和 Longcat 历史条件、删除无消费者的 GO_BASES；用独立期望驱动既有设置 UI，验证两个预设的显示、表单和保存 payload。
- [ ] 1.2 增强旧 Go 配置调整输出后的 lost-ack/remount 回归，验证原地址、模型、协议和 request ID 未迁移，已发送配置仅一次；保留既有 Responses 和 Longcat 恢复回归。

## 2. Integration

- [ ] 2.1 运行 npm run check、生产与完整 npm audit、OpenSpec validate，记录结果及可用浏览器的实际验证；由主代理核对最终差异和回执后勾选，真实 Go 调用及 PostgreSQL 未执行不记通过。

本次只修改既有配置和测试，不涉及跨模块设计或迁移，跳过可选 design.md。方案先以精确本地提交交给非作者审查；实施者不勾选任务，由主代理按现有 coordinator 指引验收。只读官方文档已在 2026-11-05 核对：GPT 6 Luna 的 `/responses` 与 DeepSeek V4.1 Flash 的 `/chat/completions` 共享 `/inference/go/openai/v1` 基础地址。
