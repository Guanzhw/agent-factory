# Proposal

## Why

审计 R4 确认，当前 Research 页面可以将新项目送入任意应用/mode 的历史首轮路径，形成无 research_rounds 和终态交付链的执行。现有 start 又先看当前组件是否匹配，导致升级后原 round 请求可能被误路由为 legacy 请求。

## What Changes

- 新 Research 准入只接受当前安装的完整研究 Workflow pin；不匹配的模式清晰拒绝，页面只提供实际兼容的发布版本/mode。
- 以持久 owner/request 命令及其原指纹判别原请求；历史 legacy 和 round 请求先恢复原 intent/receipt，不按当前配置改路由。
- 收缩历史服务为原请求恢复、读取和取消所需职责；未装研究 Workflow 时也不允许公开入口创建新历史首轮。
- 保留原 request/task/run/allocation/pin、历史记录及 UNKNOWN 占用；不宣称缺失旧代码的 paused 任务可以跨版本继续执行。

## Capabilities

### New Capabilities

- `research-admission`: 区分当前研究新准入和持久原操作恢复；主 specs 目录尚为空，延续既有 team-research-workflow 的固定组件、原身份和清理责任。

### Modified Capabilities

无。

## Impact

规划基线 `62614177c23c4d2cd0caf6b7c91418e74fde8ad4`。实施需等待 R1 已审代码由协调者整合为新基线，再复核此方案；本提交只含规范。预期涉及 research rounds/runs 的准入分流、公开无 Workflow 装配、ExecutionEditor/ProjectDetails 与针对性测试。复用现有 setup candidates.workflowPin，不新增 API、compatibility mode、调度器、finalizer、迁移或依赖；R2/R3 不在本 PR。
