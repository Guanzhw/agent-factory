# Proposal

## Why

基线 f25c899。真实 PostgreSQL 合成 MCP 单例观测中，每次授权 callback 执行63条SQL/44次checkout，凭据 callback 执行149条SQL/101次checkout。源码中同一次授权重复完整 execution guards 两次、绑定检查三次。减少同一边界内重复读取，保留新边界实时撤权。历史两项超时的全部因果尚未证明，不能以一次通过关闭历史问题。

## What Changes

- 个人工具每次授权统一经 Store.authorize_tool；验证可信绑定guard与原plan身份。
- 绑定guard由显式绑定方法装配，缺失或替换时拒绝执行。
- 保留credential前后检查、retained handle、预算、取消与UNKNOWN语义。

## Capabilities

### New Capabilities

- `personal-tool-authorization`: 单次工具授权去重与跨边界实时检查。

### Modified Capabilities

无。

## Impact

仅个人工具授权、ExecutionBindings方法、main装配及对应回归。不改协议/数据库/超时/GC，不新增缓存或重试机制。
