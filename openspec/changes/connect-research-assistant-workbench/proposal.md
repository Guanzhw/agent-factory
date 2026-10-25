# Proposal

## Why

长期研究助手及私密问答后端已经落地，但已确认工作台仍只有未接入说明。成员需要从同一工作台明确配置自己的助手，并向指定同事助手发送可恢复、有来源的私密问题。

## What Changes

- 接入已有稳定助手身份、QA私人草稿/明确发布、个人模型连接和有限操作额度配置，不创建第二认证、凭据或执行链。
- 在既有研究助手侧栏和团队页提供真实助手目录、单个原问题及回答；不存在的聊天历史不补造。
- 保留原请求恢复、真实来源读取与撤权后的整段回答隐藏；显式显示BYOK token/费用未计量。
- 新项目明确关联researchAssistantId；历史assistantId继续原义，不做隐式迁移。

## Capabilities

### New Capabilities
- `research-assistant-workbench`: 已确认研究工作台中的个人助手设置、定向私密问答、原请求恢复及来源可用性呈现。

### Modified Capabilities

无已归档能力修改；本change补充进行中的`add-research-assistant-qa`任务2.3，依赖其已实现HTTP/权限/预算契约，不复制业务策略。

## Impact

基线`f2dd047`。范围限`web/apps/research`、研究composition导航、相关前端测试和本规范；复用公共fetch/auth、资源页和现有应用命令恢复hook。无backend/core认证改动、无新依赖、无真实provider/GPU调用。自动相关性推送和真实团队科研价值仍按后续P7/C类独立交付，不能以本UI关闭。
