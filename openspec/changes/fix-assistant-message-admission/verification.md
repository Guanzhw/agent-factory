# Verification

## Revisions

- 基线：`62614177c23c4d2cd0caf6b7c91418e74fde8ad4`。
- 方案：`9a740d327c25021a4b07f260eb3210dca77b2baf`；作者外方案审查 PASS 后开始实现。
- 失败回归：`7945d10`，产品源码仍为基线。首次便携分类测试失败，4 个 PostgreSQL 回归均失败：容量变 rejected、端点禁用仍准入、sender 禁用后仍 dispatch、其他 plan 冒用原请求。
- 实现及测试：`f9fc6ae4fe2a952ce19c2568c4273dcaa0727a0c`；产品仅三个文件 9 增 9 删。作者外完整 diff 与简洁性审查 PASS；审查者未自行重跑 PG，不以日志替代源码判断。
- 独立审查与原始日志由协调者保留于 `/workspace/cross-pr-audit/message-admission-review.md`、`/workspace/agent-factory-fix-message-admission-evidence/`；本记录之后若再改源码，需对新 SHA 复核。

## Results

2026-10-26，本工作区运行，借用已有 `/workspace/agent-factory-cleanup/.venv/bin/python`，设置 `PYTHONPATH=platform:deployment:applications:platform/tests`。PG 使用协调者提供的独占串行 slot 与 loopback disposable server，实际版本 PostgreSQL 17.11。所有数据、模型及身份均为合成 fixture，无外部 provider 调用。

| 检查 | 结果 | 日志 |
| --- | --- | --- |
| 新增容量分类首失败 | 1 test，2 subtest failures | `baseline-portable.log` |
| 新增容量/撤权/指纹 PG 首失败 | 4 failures / 7.492s / 0 skip | `baseline-postgres.log` |
| 相同 4 PG 回归修后 | 4 PASS / 9.060s / 0 skip | `fixed-postgres-targeted.log` |
| messages、events 便携模块 | 19 PASS / 1.604s | `fixed-portable.log` |
| recovery、endpoints、replies 便携模块 | 20 PASS / 0.982s | `fixed-portable-related.log` |
| events、messages、message_recovery、budget_request PG 模块 | 31 PASS / 70.515s / 0 skip | `fixed-postgres-suite.log` |
| private_message_budget、budget_guard PG 模块 | 8 PASS / 13.567s / 0 skip | `fixed-postgres-budget.log` |
| Ruff：platform deployment applications scripts | PASS | `ruff.log` |
| Pyright：显式 `--pythonpath` 指向借用 venv | 0 errors / 0 warnings；提示本 tree 无 `.venv` | `pyright.log` |
| Python architecture checker | 504 modules / 0 violations / 0 coverage gaps | `architecture.log` |
| `openspec validate fix-assistant-message-admission --strict`、`git diff --check` | PASS | 本地命令回执 |
| fixture 清理只读检查 | `af_test_%` 数据库 0、连接 0；base 无 `af_tasks` 表 | `postgres-cleanup.log` |

PG 回归执行命令为 `python -m unittest -v test_assistant_events_postgres test_assistant_messages_postgres test_assistant_message_recovery_postgres test_assistant_budget_request_postgres`，以及 `python -m unittest -v test_private_message_budget_postgres test_assistant_budget_guard_postgres`，环境额外设置协调者的 `FACTORY_TEST_DATABASE_URL`。新容量测试阻塞两个真实 native task 至实际 Store 429，随后释放并观察完成，原 event/delivery/message/request/allocation 恢复为一个新 task，最终 settled 且 native submit 总数严格为 3。原 UNKNOWN/reserved/restart 与端点禁用后 recover 仍不新增提交。

## Limits

本次未修改历史 rejected 记录，也未释放真正终局且无 task 的 hold；后者仍需原 admission fence 及完整无派发证据，不能靠 404 或超时推断。未跑完整 release discovery、浏览器、Windows、真实 provider/GPU 或外部协议验收。本 tree 的全 Web `npm run check` 与 npm audit 留给协调者最终精确提交 fast CI，不能把本地 Python PASS 写成这些检查已通过。
