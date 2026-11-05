# Spec Delta

## Purpose

模型快捷配置帮助资源所有者明确选择服务提供方的模型、API 协议与端点，并将这些值交给既有保存流程。预设内容更新只影响用户之后明确选择预设的新配置，已保存模型和待核对请求仍保留其原始配置及身份。

## ADDED Requirements

### Requirement: Go 预设保存当前官方端点与显式模型协议

系统 SHALL 在用户选择 Go 快捷配置时填入 `https://opencode.ai/inference/go/openai/v1`，保存时保留该配置的显式模型 ID 和协议，不调用模型。

#### Scenario: 新建 DeepSeek V4.1 Flash
- **WHEN** 用户选择原 DeepSeek Flash 快捷项并保存
- **THEN** 快捷项显示 V4.1 版本，表单和保存请求使用 `deepseek-v4.1-flash`、`chat-completions` 及上述基础地址

#### Scenario: 新建 GPT 6 Luna
- **WHEN** 用户选择 GPT 6 Luna 快捷项并保存
- **THEN** 表单和保存请求使用 `gpt-6-luna`、`responses` 及上述基础地址

### Requirement: 预设更新保留已有配置与原请求

系统 SHALL 保留旧 saved 配置及 pending 原请求的地址、模型、协议、凭据引用和请求身份；调整输出额度不得顺带迁移配置，恢复不得重发已发送操作。历史 Longcat thinking 元数据仍只对原地址、模型与 Chat Completions 组合有效。

#### Scenario: 旧 Go 配置调整输出并恢复
- **WHEN** 旧 `https://opencode.ai/inference/go/v1`、`deepseek-flash` 配置调整输出额度后回执丢失，用户刷新并核对原保存
- **THEN** 保存及保留的 pending 元数据保持原地址、模型和协议，恢复查询原 request ID，已发送的配置请求只发送一次

#### Scenario: 历史 Longcat 配置
- **WHEN** 用户读取或恢复原 `https://opencode.ai/zen/go/v1` 的 Longcat 配置
- **THEN** 既有受限 thinking 元数据条件继续生效，不因新预设地址扩大适用范围
