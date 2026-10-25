# Spec Delta

## Purpose

研究应用在成员选定的文本模型上使用明确的 JSON 文本协议取得决策；结构验证和证据检查仍发生在原执行边界，避免向不支持 provider-native structured output 的适配器发送该格式参数，也不以解析回退扩大执行权限。

## ADDED Requirements

### Requirement: 明确 JSON 文本决策协议

研究决定与评价步骤 SHALL 将精确 schema 和分支规则作为文本指令，不设置需要 provider response_format 的 Agent output_schema，不替换用户选定模型。

#### Scenario: 真实成员模型适配器返回合法决定
- **WHEN** 原生研究 Workflow 经真实 OwnerChatModel 请求，合成 HTTP 返回合法 JSON 文本
- **THEN** 请求不带 response_format，原模型选择、凭据当前检查和原治理预算边界保留
- **AND** 原 launch/record 边界成功验证后才继续对应动作

### Requirement: 无效模型文本不得触发实验

系统 SHALL 保持原 Decision/Evaluation 严格解析及领域证据检查，不自动修补、重试、调用额外解析模型或切换模型。

#### Scenario: 无效决定
- **WHEN** 模型返回非法 JSON、缺失必需字段、额外字段或无证据达标决定
- **THEN** 原步骤明确失败，零 child launch，不伪造停止或最终决定

#### Scenario: 有效停止与评价
- **WHEN** 合法 stop 决定或来自原证据的 Evaluation 返回
- **THEN** 原 stop 无 child，评价仅通过原校验后持久化
- **AND** 无效 Evaluation 不提交最终决定，也不创建后继任务
