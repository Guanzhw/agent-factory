# Verification

## Scope and revision

实现基于 `f25c8992f5c286db3cca3554e3c74a255dfe9f82`，spec 初始提交为 `6ce1e89`。本文记录本地实现工作树；最终提交与独立审查由协调器绑定，不将当前未提交 diff 称为已发布或已合并。

只使用本机一次性 PostgreSQL、原生 Agno 队列与合成模型。checksum 工具实际计算输入字节并持久 artifact；模型输出是确定性 fixture，不能计为 C 类真实自主研究或 D 类远端 GPU 验收。没有新 worker、外部模型或远程 placement。

## Behavioral evidence

| 检查 | 结果 | 直接观察 |
| --- | --- | --- |
| Portable adapter protocol | 9 passed | 原operation/context/pin/handle约束；lookup不create；丢回执；输入冲突/额外authority拒绝；子树stop proof；清理错误明确503 |
| PostgreSQL adapter 第一轮 | 4 passed | 实际child工具结果/产物；原lookup只恢复；撤权后原child取消且newcreate拒绝；缺link保持UNKNOWN；取消先锁/创建先锁两种barrier交错 |
| 实际Workflow暂停与服务硬重启 | 1 passed, 35.689s | 原root run/operation/child保持；相同reconcile命令复用持久receipt；后续模型接收真实checksum结果；root只一native ticket、单scope单allocation指向root |
| 真实cleanup错误回执增补 | 1 passed, 5.899s | observer原cancel故障时503，custody仍cancelRequested/open/原handle；恢复后只停止原child |
| Static | passed | Ruff；Pyright 0 errors；Python architecture 433 modules, 0 violations, 0 coverage gaps；OpenSpec strict valid |

原生重启场景不将动态workflow状态误作不可变回执；比较持久command receipt，同时单独验证最终原生状态、唯一派发与实际结果。

## Preserved first failures

1. 无网络 sandbox 的组合 discovery 在 asyncio runner executor shutdown 等待（没有配置 PG）；人工 SIGINT，exit 130。此前单独 portable 可通过。带明确 loopback 执行权限运行后通过，没有改变产品超时。
2. 第一轮 `12 tests / 54.843s`：11 passed，1 failed。新restart测试比较整个command响应，实际实时workflow投影从PAUSED变为RUNNING；修正为比较持久receipt，保留实际状态变化/最终结果断言。
3. 增补scope fixture后的单项 `1 test / 23.970s` 在派发前失败：`LOCAL_BUDGET_REQUEST_PLAN_CONFLICT`。fixture只bind_request而未调用既有admit_plan记录原request→plan关联。修复fixture装配后单项通过；不修改准入校验。
4. 首次针对静态检查有一项handle类型注解错误，补充已有输入类型后Pyright为0。第一次architecture命令漏 `--config`，exit2；使用仓库配置后通过。

本地原始日志：`/tmp/af-delegated-operations-evidence/first-pg.log`、`restart-after-oracle-fix.log`、`restart-bound-request.log`、`portable-final.log`、`cleanup-error-final.log`。测试退出时清理自己的临时数据库、进程、fixture目录；UNKNOWN缺link用例保持未知事实直到一次性数据库退出，不注入假的stop proof。

## Independent review remediation

两项阻断整改均已追加定向验证：

- 普通create不能声明保留`operation:`request；trusted原operation同时核固定pin。公开HTTP使用已取消、尚无child的原request，返回409且零child/dispatch。
- 子树停止观察在同root锁内重读关联和facts。真实descendant创建持锁至link提交期间，inspect必须等待；释放后包括新后代并保持非allStopped。

定向真实PG `2 tests / 9.372s` 全通过，exit0，日志 `review-targeted.log`。便携9项日志 `reserved-request-portable.log`。原native重启验收未因这两项修复机械重复；最终组合检查由协调器安排。独立复审结论尚待协调器登记。

## Commands

```sh
PYTHONPATH=platform:platform/tests:deployment:applications .venv/bin/python -m unittest test_delegated_operations -v
# FACTORY_TEST_DATABASE_URL 指向协调器分配的本机一次性PG；重型检查串行。
PYTHONPATH=platform:platform/tests:deployment:applications .venv/bin/python -m unittest test_delegated_operations_postgres test_delegated_workflow_native_postgres -v
.venv/bin/ruff check platform/agent_factory/delegated_operations.py platform/agent_factory/delegation.py platform/agent_factory/lifecycle_observer.py platform/agent_factory/main.py platform/tests/test_delegated*.py platform/tests/test_native_workflow_factory_postgres.py
.venv/bin/pyright platform/agent_factory/delegated_operations.py platform/agent_factory/delegation.py platform/agent_factory/lifecycle_observer.py platform/agent_factory/main.py
python scripts/check_architecture.py --config scripts/architecture-python.json
OPENSPEC_TELEMETRY=0 npm --cache /tmp/agent-factory-openspec-cache exec --offline --package=@fission-ai/openspec@1.14.3 -- openspec validate bind-delegated-workflow-operations --strict
```

最终必要完整检查、精确head独立精简review尚由协调器整合。现有scope入口guard回归与整体生命周期回归不能由本表的mock替代。RuntimeObservation保持原有inert大小/文本约束，任意正文需走artifact读取；本变更不扩大协议、前端或远程能力。
