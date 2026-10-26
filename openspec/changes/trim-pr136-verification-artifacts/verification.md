# Verification

## Revision

- 基线：`62614177c23c4d2cd0caf6b7c91418e74fde8ad4`；本地实现候选：`1eb12f16c998777d4fb7eaf5702af611242773d1`。本记录后续提交仅增补文档，不改变被测源码。
- 先审方案：本地 `ed067f7926f35484be31810426c41d1be05c0429`；插件发布 `5df68e7bd5417b41ceab4a9f840200e88f1a55d0`，二者 tree 均为 `450a1cdd98ecc6780f4de7c783a3258fe4191f83`。独立方案结论见 [review.md](review.md)；不把不同提交 SHA 当作相同提交。

## Results — 2026-10-26

| 检查 | 首次结果 | 证明边界 |
| --- | --- | --- |
| `ruff check platform deployment scripts`、`pyright` | PASS；0 errors/warnings | Python 静态检查 |
| OpenSpec strict、`git diff --check`、`uv pip check` | PASS；68 包兼容 | 规范、空白和锁定环境兼容；未变更依赖 |
| 两份删除的 MCP JSON 对比固定历史对象 | 逐字节相同 | `a02438e17316f4b748b2ed6624fe920bc449050f` 保留完整轨迹；原失败未闭环结论仍在原文字记录 |
| 浏览器归档和生成器 | PASS | 子报告/截图与基线逐字节相同；实际 `main` 的报告写入段在合成 `run_mode` 下核对 desktop/mobile/both 路径；不是新浏览器验收 |
| 原 `StorageProcessTests`，默认模式 | 1/1 PASS，0 skip，7.578s | 普通 worker；无诊断文件或保留目录；原 quarantine、退出、恢复断言 |
| 同一 storage 测试，`FACTORY_STORAGE_DIAGNOSTIC=1` | 1/1 PASS，0 skip，6.707s | 诊断 worker；保留 jsonl/stacks；相同原测试、原 15 秒 HTTP 截止时间 |
| fixture lifecycle + department publication + identity | 34/34 PASS，0 skip，22.269s | 17 便携测试；13 发布和 4 身份真实 PG 测试，包括 owner 隔离、disabled/revoked、无 IdP 拒绝和旧 demo 数据库拒绝 |

PostgreSQL 使用 CI 相同的 17.11 固定镜像，仅绑定本机 loopback，每项测试自建随机数据库。两次 storage 运行通过外部 teardown 观察器检查 worker、文件、原超时和清理，未修改测试正文或断言；各运行一次，无重试。子进程退出、工作目录和数据库移除均确认；最终 `af_test_*` 为零、其它 client 为零，一次性容器已停止并自动移除。

本机原始回执保留在 `/tmp/pr136-storage-{default,diagnostic}-first.log`、`/tmp/pr136-fixture-identity-publication-first.log`；观察器为 `/tmp/pr136-storage-observe.py`。诊断保留目录 `/tmp/af-storage-cancel-diagnostic-0xg49j8o` 未纳入 Git。相关原测试命令：

```sh
PYTHONPATH=platform:deployment:platform/tests uv run python -m unittest test_storage_process.StorageProcessTests -v
FACTORY_STORAGE_DIAGNOSTIC=1 PYTHONPATH=platform:deployment:platform/tests uv run python -m unittest test_storage_process.StorageProcessTests -v
PYTHONPATH=platform:deployment:platform/tests uv run python -m unittest test_native_fixture_lifecycle test_department_publication test_development_login_postgres -v
```

命令需先设置授权的一次性 loopback `FACTORY_TEST_DATABASE_URL`。本次全部行为检查首次通过，零跳过；历史失败没有重分类。最终候选独立完整 diff 复审及发布后精确 head CI 仍由协调者核验。没有新浏览器、真实模型/GPU、生产 IdP 或部署验收结论。

## Audit Q2 follow-up — 2026-10-26

方案 `4ac2bb06d20aa0cb5aeb16b99a3f1c261bf6e3eb` 经 `audit_quality` 非作者 PASS 后，执行实际 `accept_research_assistant_ui.main` AST 与合成 browser/run ports。旧实现的 desktop/mobile/both 均因 aggregate 重复正文失败（exit 1）；仅改三处报告写入后，三个索引均可读取完整子报告，另一个故意失败场景继续抛出异常、不写成功汇总，四次 browser close 均执行（exit 0）。`run`、历史报告、截图和产品代码不变；未重新运行 PG 或真实浏览器。窄复现与两份输出保留在工作区 `audit-remediation/q2-probe.py`、`q2-first-failure.log`、`q2-passed.json`，不将原始输出入库。

Ruff、完整增量 whitespace 和项目配置 Pyright 均通过。额外显式检查此配置外浏览器脚本出现 7 个诊断（缺 browser/test imports 及既有类型问题）；以 `fdb78b5` 原脚本对照后诊断逐字相同，仅文件名不同，不将该额外检查说成通过，也不顺带修改原验收逻辑。最终 Q2 实现和文档增量仍需非作者完整复审；PR139 保持 Draft，历史审计结论不被此次窄修正覆盖。
