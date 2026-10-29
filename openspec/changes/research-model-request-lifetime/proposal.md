# Proposal

## Why

公开仓库修复任务暴露了个人模型适配器独立的 30 秒请求期限；本地 31 秒响应已复现被截断，现有原生任务配置却允许继续等待。需要消除这个人为中断，同时保留取消和同步摘要请求的有限等待。

## What Changes

- 个人模型请求使用已有 `Settings.native_timeout_seconds`，删除独立 HTTP 10 秒限制，不新增用户字段或环境配置。
- 保留 Agno 3.1.0 原生运行期限、取消传播、当前权限核查及零自动重试。
- 用确定性超时/取消反例与真实 Go 仓库任务分别验收；之前失败和未知响应保留。

## Capabilities

### New Capabilities

- `owner-model-requests`：个人模型请求的等待、取消及未知响应边界。

### Modified Capabilities

无；当前仓库尚无已归档 capability spec。

## Impact

基线 `40985ab837a0c01b35f490482f2c55e9e5b9c1e0`。修改 core 的 `byok_model.py`、`personal_models.py` 及针对性测试；不改数据库、模型协议、应用 UI、依赖或独立 broker 路径。旧冻结候选及其发布门禁保持不变。
