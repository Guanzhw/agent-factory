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

## Native consumer first attempts

已集成core reply已审序列`207bf39/7809462/31b1faf/764aa6f`（本分支等价`ef0382b/3012f3d/ea5b09c/62db666`）。实际QA consumer尚未PASS：

- `/tmp/research-qa-native-collection.log`首次collection因fixture引用factory_state模块错误失败，改为实际deployment.main后正常collect（未提供PG时显式skip）。
- `/tmp/research-qa-native-first.log`：1 fail，5.016s。fixture声明finite metered caps和synthetic pricing却漏启用fee管理，配置409 `LOCAL_BUDGET_METERING_UNAVAILABLE`，模型未调用。
- `/tmp/research-qa-native-metered.log`：fixture明确`fee_management_enabled=True`后1 fail，4.865s，准入409 `Current registered execution binding inspection denied`。定位core `billing_mode.require_available`将非local pricing视作managed，而`ledger_for_plan`对owner BYOK固定返回None；因此当前“owner模型实际调用+scope计量”不能以设置pricing当作已支持。已向core coordinator报告，未开启platform paid权限、未改为无限或去掉usage断言。
- 两次均为一次性PG数据库，TestClient/lifecycle正常关闭，PG槽已释放。Registry报告QA与research函数/输入schema同名，随后给QA函数及输入类型独立名称；相应portable6项通过（`/tmp/research-qa-unique-registration.log`）。

身份作者额外证据：PG初轮3项中2 pass、1fixture缺真实Store schema error，补fixture后targeted1 pass；P2 disabled-recipient恢复先403反例失败，修复`cacfecd`后portable6 pass及实际PG目标1 pass/1.452s。这些分次证据不冒充最新head完整组合通过。

## BYOK boundary correction and actual successful consumer

源码独立核对后采用既有BYOK不入平台账务边界，规范`bdb3d22`先修正错误前提：当前QA显式finite rounds/toolCalls/deadline，tokenLimit/amountMicros/currency必须null；非null请求明确拒绝，配置返回“操作额度受限，token/费用未计量”。不以本路径解除硬token/费用验收，不开启platform-paid或宣称实际费用受控。

- `/tmp/research-qa-native-byok-first.log`：1 fail/5.016s；此前为消除Registry类名警告而重命名输入类，使JSON schema title与core生成模型不同，准入明确`NATIVE_WORKFLOW_INPUT_SCHEMA_CHANGED`。撤回类重命名，保留QA治理函数唯一名称，不改core身份/模式校验；共享input helper类名警告仍如实保留。
- `/tmp/research-qa-native-byok-fixed-schema.log`：实际native QA 1 passed/8.166s、0 skipped、exit0。真实研究部署/HTTP发布/配置/原消息准入→实际OwnerChatModel合成HTTP一次→本地Answer校验→原reply；两个输入来源全部绑定、私有canary不进模型、未引用B撤回隐藏整个答案。原scope仅1round，第二问题429且零新增task/模型请求，零delegation child。
- 该成功使用明确BYOK操作额度，不是UsageLedger计量验证，也不是真实模型质量/C03通过。provider返回恶意train tool_call的有界失败仍待验证；Agno未知工具循环风险已报告core，不用普通源文本恶意提示替代此反例。
