# 验证记录

基线551f1bf，规范先行1ff7d4e。只改夹具一行：`store.local_budget_scopes = None`；真实Store该服务默认即None。无产品/原断言改动。

- 首次Windows完整失败：`/tmp/af-qa-full-first-windows.log`，2029项、7 errors、822 skips；不改写其失败结论。
- 本地首复现：`PYTHONPATH=platform:platform/tests timeout 30 /workspace/agent-factory-research-next/.venv/bin/python -m unittest test_lifecycle_terminal_race -v`，10项、7 errors、0.031s，退出1；`/tmp/lifecycle-terminal-fixture-before.log`。
- 修后：同环境 `timeout 60 ... -m unittest test_lifecycle_terminal_race test_application_runtime -v`，28/28、零跳过、0.039s，退出0；`/tmp/lifecycle-terminal-fixture-after.log`。
- Ruff、git diff --check通过。没有PG/full重跑，没有改变生产超时、默认值或终态规则。

旧69d798b通过的原因通过源码对比确认：当时Store.completion_context仅检查空应用registry；新代码新增budget-only fallback，裸Mock的未配置属性冒充预算服务。terminal KeyError是错误路径的症状，不是需要产品兜底的字段兼容问题。便携结果不冒充Windows完整或新head完整验收；独立review和集成检查由协调者继续。
