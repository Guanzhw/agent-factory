# Verification evidence

## Scope and preserved logs

基线 `62614177c23c4d2cd0caf6b7c91418e74fde8ad4`；方案 `114391f1906242e4d0eae3f8c305773d5c807dcf`；最终产品/测试源码 `342028fa3d182eee57c8873a992a400a02972b1f`。非作者已审完整累计 diff 并给出最终实现 PASS，另独立运行 14 项合同/custody 回归通过，详见 [review.md](../review.md)。任务勾选及组合验收归 coordinator。

5 份原始文本日志（before.txt、before-depth.txt、portable.txt、portable-depth.txt、postgres.txt，共 288 行）按归档时原字节保全到 `/workspace/audit-remediation/c1-raw/`，逐文件与提交 `da9e3cf9e530d0ba5a12c3587a5c4be8211c19ae` 的内容核对相等后才从当前树移除。本地目录不随仓库分发；完整日志仍可从该精确提交的本 evidence 路径恢复，例如：

```sh
git show da9e3cf9e530d0ba5a12c3587a5c4be8211c19ae:openspec/changes/separate-delegated-result-content/evidence/before.txt
```

未重写 Git 历史。最初失败日志在较早修复中只清过行尾空格；本次归档不再改变任何日志字节。仓库保留结构化回执及以下失败/通过摘要。

## Failure and correction

首次失败回归提交 `032039ecaf1df386bdfc46b6e614ea67d8bfeacf`：换行、URL、较大中文正文、普通业务键四个 subtest 均报 `WORKFLOW_CONTRACT_INVALID`。[before.json](before.json) 记录同一原 operation 连续两次 lookup 均 `closed=false`、held、effect UNKNOWN。

独立审查 `0299819b965723868d910bb21fb55de2155bdef6` 又发现：500 层、1006 字节 JSON 编码后在 deepcopy 失败。深度方案增量 `7c16722d7d736241267fcf1dc42a56ab14cc1a27` 经非作者 PASS 后才实施。[before-depth.json](before-depth.json)／[after-depth.json](after-depth.json) 保留对照：修前 500 层 held/UNKNOWN；修后 64 层完整 COMPLETED，65/500 层明确 FAILED／`DELEGATED_RESULT_INVALID`，全部 closed/effect DONE，每例只派发一次。

以上使用实际 DelegatedOperations、OperationCustody 和 Store SQLite 事务/effects；child admission、observer stop facts、artifact listing 为合成输入，不是 PostgreSQL/native 执行证据。两个首失败用例的精确命令（从对应源码阶段的仓库根运行）为：

```sh
PYTHONPATH=platform:platform/tests /workspace/agent-factory-cleanup/.venv/bin/python -m unittest test_delegated_content.DelegatedContentTests.test_normal_content_closes_original_and_survives_custody_restart -v
PYTHONPATH=platform:platform/tests /workspace/agent-factory-cleanup/.venv/bin/python -m unittest test_delegated_content.DelegatedContentTests.test_nested_data_boundary_closes_original_without_copy_failure -v
```

## Portable and static checks

初次修复 50 tests PASS；深度修正后 52 tests、0 skipped、PASS，涵盖完整正文、原消费者、预算边界、格式/深度失败闭合及 UNKNOWN 保持。Research 消费测试使用现有 fake execution ports。命令：

```sh
PYTHONPATH=platform:platform/tests:applications:applications/tests /workspace/agent-factory-cleanup/.venv/bin/python -m unittest test_delegated_content test_delegated_operations test_workflow_contracts test_workflow_operations test_workflow_control test_research_rounds -v
/workspace/agent-factory-cleanup/.venv/bin/ruff check platform deployment applications scripts
/workspace/agent-factory-cleanup/.venv/bin/pyright --pythonpath /workspace/agent-factory-cleanup/.venv/bin/python
/workspace/agent-factory-cleanup/.venv/bin/python scripts/check_architecture.py --config scripts/architecture-python.json
```

Ruff PASS；Pyright 0 errors/0 warnings/0 informations（提示本 tree 无 `.venv`，已显式使用共享解释器）；架构检查 505 modules、0 violations、0 coverageGaps。未改依赖，前端综合检查与依赖审计由 coordinator 统一执行。

## PostgreSQL

coordinator 授予独占临时 PostgreSQL 时隙后，在精确源码 `803c00a0e7158830b6fedaa2b8496222cdac30e6` 执行：

```sh
FACTORY_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55432/postgres PYTHONPATH=platform:deployment:platform/tests:applications:applications/tests /workspace/agent-factory-cleanup/.venv/bin/python -m unittest test_delegated_workflow_native_postgres test_delegated_operations_postgres -v
```

[postgres.json](postgres.json)：PG17.11，6 tests、0 skipped、18.317s、PASS。真实 child 工具产出含换行/URL/中文/业务 token 字段的正文（>32 KiB，低于原 64 KiB 预算）；原 paused workflow 硬重启后 custody 与 parent 最终 native content 中的原 wait 结果完整等值，原身份和单次 continuation 保持，custody closed、effects DONE、原 allocation SETTLED。原 lost ack、撤销/取消、UNKNOWN 与并发停止边界也通过。

执行了实际 PostgreSQL/native queue/tool/workflow/custody/预算结算；模型为 deterministic fixture，lost ack、取消失败和并发屏障为注入 seam。没有真实模型、付费资源、GPU 或 SSH 作业。结束后临时 `af_test_%` 数据库与相关 Python fixture 子进程均为零，共享容器及依赖未改，时隙已归还。

深度修正未复跑 PostgreSQL：原 PG result 为 string，新增递归结构规则不改变该路径；这 6 项证据仅归属 `803c00a`，不冒称最终 head 实测。新增深度边界由实际 SQLite custody/effect 回归验证，组合执行由 coordinator 安排。
