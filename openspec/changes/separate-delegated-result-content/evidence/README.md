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

coordinator 授予临时 PostgreSQL 独占时隙后，在源码精确 head `803c00a0e7158830b6fedaa2b8496222cdac30e6` 运行：

```sh
FACTORY_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55432/postgres PYTHONPATH=platform:deployment:platform/tests:applications:applications/tests /workspace/agent-factory-cleanup/.venv/bin/python -m unittest test_delegated_workflow_native_postgres test_delegated_operations_postgres -v
```

`postgres.txt`：6 tests，0 skipped，18.317s，PASS。`postgres.json` 保存精确源码 head、PG17.11 版本、证据边界与 cleanup 查询。真实 child 工具产生的正文含换行/URL/中文和普通业务 token 字段，UTF-8 超过 32 KiB、低于原 64 KiB 预算；原 paused workflow 硬重启后，持久化 custody 与 parent 最终 native content 中的原 wait 结果完整等值，原 child/operation/run 身份及单次 continuation 保持。实际 `closed=true`、effects DONE、原 scope allocation SETTLED；lost ack、撤销后原取消、UNKNOWN 不重派、创建/取消交错、未决 descendant 原边界通过。

实际执行 PostgreSQL/native queue/tool/workflow/custody/预算结算；模型为 deterministic fixture，lost ack/取消失败/并发屏障为注入 seam。没有真实模型、付费资源、GPU 或 SSH 作业。结束后 `pg_database` 中 `af_test_%` 数量为零，相关 Python fixture 子进程为零，共享容器及依赖未改，时隙已归还 coordinator。日志中的 403 撤销错误为已有边界测试的预期路径，测试本身通过。
