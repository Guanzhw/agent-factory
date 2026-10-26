# Proposal

## Why

基线 `d9f92acffcfd6937c4c43ad8c3ddc205e6e1b9f6`（依赖 R1，须待其独立实施审查 PASS）仍把全部终稿复制进 16 KiB manifest 校验。两个合法约 7.5 KiB 终稿即可使 create 抛未处理 ValueError/HTTP 500；ZIP 原上限还未包含自身头部。审计 R2 要求正常多轮完整交付与真正超限可区分。

## What Changes

- manifest 只持久完整不可变 recordIds/sourceIds 与原元数据；按当前授权解封原终稿，read/UI/download 的 records 完整。
- 创建时校验完整 UTF-8 manifest、精选附件及 ZIP 头部共同受既有 delivery 上限约束；真实超限返回 413，无半成品回执。
- 旧含 records 副本的 manifest 保留，读时仍核对原来源并还原相同 records；不回填、不裁剪、不重复导出 R1 正文载体。

## Capabilities

### New Capabilities
- `research-delivery`: 原来源授权下的完整成果快照与有界导出。

### Modified Capabilities
无；当前规范库无此项正式 spec。

## Impact

仅 `applications/research/delivery.py`、定向便携/PG 测试与文档。API 字段保持，核心内容接口与 Research workflow hash 不变。R3 ending 和 R4 新准入分别实施。
