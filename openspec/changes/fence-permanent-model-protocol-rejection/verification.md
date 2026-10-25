# 验证记录

基线551f1bf，规范先行1a3545b；独立规范审查后补admission→task锁序再实施。没有修改Agno、queue attempts、observer算法或产品超时。

## 原失败与根因实验

原full日志 `/tmp/af-qa-full-first-pg.log`。隔离原源码单例1test/1failure10.513s（`/tmp/qa-retry-single-first.log`）；正常→恶意组合2tests/1failure22.725s（`/tmp/qa-retry-pair-first.log`）。实际同job的attempt1/max_attempts2后attempt2/max_attempts2，模型各请求一次；不是跨测试泄漏或模型内部工具循环。两次失败均保留。

## 实施

可信模型调度仅识别ModelProviderError精确安全code。Store事务先af_admission、再task+owner+run行锁，记录protected_denied并复用request_cancel；提交后传播错误。下一原队列attempt不再进入provider/tool。四种入口保留账务完成；账务与栅栏即使一方抛错另一方仍尝试，同时异常通过上下文保留。异步事务用to_thread。observer按原protectedfailure得出failed，UNKNOWN/结算仍走原流程。

## 检查

- Portable：`PYTHONPATH=platform:platform/tests timeout 60 .../python -m unittest test_model_protocol_fence test_async_authority test_byok_tool_authority test_byok_native_wait test_byok_model -v`，29/29、零跳过、0.461s、退出0；`/tmp/qa-fence-portable-first.log`。
- 新PG首轮：2tests/1error16.245s。原行为断言已通过，Store重开测试错误地清理未装配的native_db(None)；删去该不存在资源cleanup，未改产品或通过断言。日志 `/tmp/qa-fence-pg-first.log`。
- 修后PG：`PYTHONPATH=platform:platform/tests:applications:applications/tests:deployment timeout 120 .../python -m unittest test_research_qa_fence_postgres test_research_qa_postgres -v`，4/4、零跳过、30.143s、退出0；`/tmp/qa-fence-pg-final.log`。
- 新PG确实hold observer直至原queue attempt2结束，断言attempts=[1,2]、同job/session、max_attempts2；恶意仅1HTTP/零工具/原任务failed+原protected_denied，Store重新构造后栅栏仍在。普通首transport失败允许第二HTTP并完成；同事务中故障回滚与错误owner/task/run均不改状态。
- 原QA测试的恶意计数仍要求1，正常计数仍1；新增明确transient fixture才要求2，作为保留合法重试的负对照。
- Ruff/diffcheck通过。目标两个产品文件Pyright 0 errors/0 warnings，退出0；`/tmp/qa-fence-pyright.log`。

本轮仅便携和隔离真实PG/nativequeue+合成HTTP，不是外部模型/GPU验收。数据库写入失败时不宣称成功持久化栅栏；保持明确异常，不使用内存替代或无界重试。没有全量重跑。独立精确head审查、合并与最终集成验证由协调者继续。
