# 验证记录

基线 1ed1d72；规范先行 6dbccac。仅 OwnerChatModel SDK→provider 边界复制移除已知布尔字段，canonical codec 与原生等待工具无改动。

- `PYTHONPATH=platform:platform/tests timeout 60 .venv/bin/python -m unittest test_byok_native_wait test_byok_model -v`（实际复用 research-next venv）：12/12，零跳过，0.230s，退出0；日志 `/tmp/owner-tool-metadata-final.log`。
- 新测试使用真实 Agno Agent、factory_wait_operations、OwnerChatModel 和合成 HTTP transport。两协议均触发原 requirement 的 external_execution_required，暂停后完成该 requirement、恢复相同 run_id；请求不含本地字段，原工具与传入字典不变。布尔 false 同样适配；非布尔及其他未知字段拒绝、零 HTTP。
- Ruff、git diff --check 通过；产品文件定向 Pyright：0 errors/0 warnings，退出0；日志 `/tmp/owner-tool-metadata-pyright.log`。
- 首轮 `/tmp/owner-tool-metadata-first.log` 在首用例已输出 ok 后停于 runner teardown；restricted network 且 fixture 未禁 Agno telemetry。约23秒后终止自己的 PID182838，确认进程已不存在。fixture 设置 telemetry=False 后以本地网络许可有界复验；未改变产品超时或通过条件。首轮未完成，不计通过；未采集线程栈，不将遥测解释断言为已完全证明根因。

未运行 PostgreSQL、实际外部 provider 或 GPU。合成 HTTP 与便携 Agno 生命周期不能替代这些边界。独立完整差异审查由协调者确认，任务勾选仍由协调者负责。
