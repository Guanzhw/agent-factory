# Verification

本地实现，未发布；原基线`3b467519`，规范`6e8c965`、原问题恢复修订`c709c14`，身份实现`f292e33`/负例`8e74c18`，QA consumer与装配`996127f`。本记录不把机制测试当真实模型研究价值或GPU验收。

## Executed

- `openspec validate add-research-assistant-qa --strict`：exit 0。
- QA、QA setup、旧project迁移及project回归：14 passed，0 skipped，1.910s，exit 0。命令：`PYTHONPATH=platform:platform/tests:deployment:applications:applications/tests timeout 60 python -m unittest test_research_qa test_research_qa_setup test_research_assistant_projects test_research_projects -v`。
- 其中实际Agno Agent + `OwnerChatModel` + `httpx.MockTransport`验证JSON文本输出到本地Answer校验，1次请求、无`response_format`、无tools。此为合成HTTP协议验证，不是正式模型调用。
- 当前应用源码Ruff：exit 0。限定当前源码/venv的Pyright：0 errors，0 warnings，exit 0（60秒限额，未留下运行进程）。
- `python scripts/check_architecture.py --config scripts/architecture-python.json`：460 modules，0 violations，0 coverage gaps，exit 0。

## First failures retained

- `/tmp/research-qa-portable-first.log`：新测试误用registration.workflow，实际契约为component。修正测试字段，不改产品门槛。
- `/tmp/research-qa-portable-second.log`：QA没有实验材料但复用closure(empty)触发既有拒绝；改为QA明确空实验集合。另项目change批量编辑误访问CreateProject专有字段，恢复change路径，只create纳入新关系。修复后原project完整回归通过。
- `/tmp/research-qa-portable-third.log`及`/tmp/research-qa-portable-current-final.log`保留必要复验；没有加长超时、放宽断言或重复整套追绿。

## Pending

- core原reply最终审定提交尚待集成；应用不复制答案表或反向send兜底。
- `test_research_qa_postgres.py`已编写实际部署/HTTP/原生队列、合成owner模型/定价/有限预算用例，尚未运行。PG须按协调槽串行；未运行不得记PASS。
- 作者外完整diff审查、实际浏览器QA、真实C02/C03模型/任务/预算参数和D资源验收尚未完成；主动关联仍后续P7任务。
- 当前测试计时仅运行记录，不是无争用性能基线或整体加速证据。
