## Why

基线 `62614177c23c4d2cd0caf6b7c91418e74fde8ad4` 的 R1 独立审查已复现：合法的 1587 字中文约定与 1900 字 stop 理由组合成 21226 字节的转义 JSON，完成时超过 core 的 16 KiB 内容限制。原终态与结算同事务回滚，重试不能改变已经保存的决定。

## What Changes

- 保留现有 16 KiB inline publication；内容接口增加互斥的 `contentArtifact` 正文引用，长研究终稿使用现有原任务 artifact 保存完整 UTF-8 JSON。原 20 个精选证据附件仍独立，不建立第二内容存储或恢复框架。
- artifact、publication、原研究终态和预算结算仍在原完成事务；旧已保存的大决定在原身份上恢复，不要求重跑模型。
- 正文采用既有单 artifact 字节预算，结构和安全数据校验保持；真正超出该预算时记录明确发布失败并保留原证据，不伪造科学失败，也不无限卡住已停止任务。
- 原 content read/list 在授权后解封，QA、关联、后继、交付取源和 UI 无须换正文接口。R2 的多轮清单结构和 R3/R4 留给后续独立变更。

## Capabilities

### New Capabilities

- `research-record-publication`: 完整、有界且可恢复的研究记录发布及当前权限下读取。

### Modified Capabilities

无已归档主规范；本要求补充现有 `restore-team-research-application` 和 `deliver-selected-research-evidence` 变更，不替代原停止、来源与公开字段限制。

## Impact

范围为 core `application_content.py` 的正文引用/API模型与 `input_schema.py` 保持默认兼容的 UTF-8 字节校验选项，Research 终态发布及精确旧 pin 完成装配、正式 UI 发布失败状态。复用 Store 的事务型 `artifact_write`、core 内容授权/哈希验证和既有输出上限。无新表、后台队列、存储服务、付费依赖或全局限额提高。
