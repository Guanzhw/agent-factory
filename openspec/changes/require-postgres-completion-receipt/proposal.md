# Proposal

## Why

基线f25c899。完整PG日志的长cat输出可能缺少末尾汇总；现有CI只验证子进程exit code。run40191804720已知执行越过MCP至storage，但完整计数未核实，不能据status成功推断验收闭合。

## What Changes

runner可选输出独立小JSON完成回执；CI在单独step验证回执并输出短摘要。提前停止不能accepted。不改变产品、测试期限或完整测试选择。

## Capabilities

### New Capabilities

- `postgres-completion`: 完整PG正常结束的独立完成证据。

### Modified Capabilities

无。

## Impact

仅check_postgres、现有runner回归及CI装配。不下载旧artifact，不追溯改变旧run结论。
