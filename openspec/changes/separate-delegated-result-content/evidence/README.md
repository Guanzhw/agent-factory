# Verification evidence

## Scope

基线 `62614177c23c4d2cd0caf6b7c91418e74fde8ad4`；方案 `114391f1906242e4d0eae3f8c305773d5c807dcf`；首次失败回归 `032039ecaf1df386bdfc46b6e614ea67d8bfeacf`。`review.md` 的 PASS 仅为非作者方案审查，最终完整 diff 另审。任务勾选留给 coordinator。

## Before

`before.txt`：未改产品源码时运行 `test_delegated_content.DelegatedContentTests.test_normal_content_closes_original_and_survives_custody_restart`，换行、URL、较大中文正文、普通业务键四个 subtest 均报 `WORKFLOW_CONTRACT_INVALID`。

`before.json`：同一个 `DelegatedContentTests` fixture 先 `original()`，再 `completed('line one\nline two')`，连续两次原 `service.lookup` 捕获该错误后分别读取原 journal、`task_held` 和 `af_effects`；均为 `closed=false`、held、`UNKNOWN`。实际使用 `DelegatedOperations`、`OperationCustody`、Store SQLite 事务/effects；child admission、observer subtree facts、artifact listing 为合成输入。未执行 PostgreSQL、native child 或真实预算结算。

## After: portable/static

从仓库根运行，Python 为共享只读环境 `/workspace/agent-factory-cleanup/.venv/bin/python`：

```sh
PYTHONPATH=platform:platform/tests:applications:applications/tests /workspace/agent-factory-cleanup/.venv/bin/python -m unittest test_delegated_content test_delegated_operations test_workflow_contracts test_workflow_operations test_workflow_control test_research_rounds -v
/workspace/agent-factory-cleanup/.venv/bin/ruff check platform deployment applications scripts
/workspace/agent-factory-cleanup/.venv/bin/pyright --pythonpath /workspace/agent-factory-cleanup/.venv/bin/python
/workspace/agent-factory-cleanup/.venv/bin/python scripts/check_architecture.py --config scripts/architecture-python.json
```

`portable.txt`：50 tests，0 skipped，PASS。实际 custody/effect 重启读取等值，UTF-8 正好预算与超一字节分别 COMPLETED／FAILED 且 effect DONE，非 JSON 明确失败，UNKNOWN 仍 held；原 wait 的 tool result 和 Research 本轮/前轮消费全文。Research 测试使用已有 fake execution ports，不冒称真实 native。

Ruff PASS；Pyright 0 errors/0 warnings/0 informations（提示该 tree 无 `.venv`，已显式指定共享解释器）；架构检查 505 modules，0 violations，0 coverageGaps。未新增或更改依赖，前端综合检查与依赖审计由 coordinator 统一执行。

## PostgreSQL

已获 coordinator 的临时 PostgreSQL 独占时隙；计划执行 `test_delegated_workflow_native_postgres` 与 `test_delegated_operations_postgres`。执行回执尚待补齐，不计为 PASS。
