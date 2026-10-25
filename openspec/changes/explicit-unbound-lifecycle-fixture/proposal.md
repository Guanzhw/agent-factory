## Why
551f1bf 完整 Windows 验收的7个错误在终态竞态夹具误入预算完成路径。本地10项测试复现7 errors。

## What Changes
显式声明未绑定预算的 Mock Store.local_budget_scopes=None，与真实 Store 初始化一致。

## Capabilities
### New Capabilities
- `lifecycle-fixture-contract`: 终态竞态夹具准确表达无预算完成owner。

## Impact
仅测试夹具；不修改生产代码、超时或原断言。
