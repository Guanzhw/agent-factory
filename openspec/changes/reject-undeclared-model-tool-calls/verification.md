# 验证记录

基线 4956857，规范先行 fa6ed5e，独立规范审查通过后实施。

首次真实 Agno 无工具 Agent 的合成 HTTP 反例：两个协议都向恶意 train 响应发起了第二次请求。fixture 第二请求立即抛出固定异常以防无界循环；测试一项含两失败子例，0.036s，unittest 失败。日志 `/tmp/owner-tool-response-before.log`；外层命令随后 cat，shell 退出0不代表该测试通过。

修复仅在原 transport try/except 外解析成功 HTTP 响应，并按本次 codec 生成的局部 wire body 校验全部返回工具名；未声明工具固定安全错误，不含原响应文本。不读取 await 后外部 kwargs，不保存共享授权集合；原拒绝/空输出错误保持原 code。

最终命令：`PYTHONPATH=platform:platform/tests timeout 60 /workspace/agent-factory-research-next/.venv/bin/python -m unittest test_byok_tool_authority test_byok_native_wait test_byok_model -v`。

- 17/17，零跳过，0.296s，退出0：`/tmp/owner-tool-response-final.log`。
- 真实 Agno Agent 两协议无工具恶意响应均仅1次HTTP、无工具执行；正常文本成功。
- 同一模型并发不同声明集合不串线；sync/async及stream委托拒绝未声明工具、保留合法工具。
- 原等待工具暂停、原requirement完成、同run恢复回归通过。
- REFUSAL/EMPTY_OUTPUT安全错误未变成transport错误。
- Ruff、diff check通过；定向Pyright 0 errors/0 warnings：`/tmp/owner-tool-response-pyright.log`。

全部为便携原生Agent+合成HTTP；未运行PG、真实模型、GPU。QA部署/完整native集成由应用作者另验，不能从本测试外推已通过。任务勾选及独立精确head审查由协调者核对。

## 首轮精确 CI 失败与夹具修正

CI [40205672388](https://github.com/Guanzhw/agent-factory/actions/runs/40205672388) 的 bb1d11b Python 370 项出现9 errors，PG通过；首次日志保留在 `/tmp/af-core-tool-response-first-ci-failure.log`，不以局部通过覆盖失败。9 errors来自5个 owner continuation/private-marker 测试首次请求未声明 checksum_fixture，却要求返回该工具。两个跨协议/legacy测试各产生3个错误子例。新增规则正确拒绝，续接断言尚未执行。

仅补5次首请求的固定工具声明，全部原断言、后续纯文本无工具请求及产品代码保持不变。完整 owner 协议相关模块与原17项合跑：

`PYTHONPATH=platform:platform/tests timeout 120 /workspace/agent-factory-research-next/.venv/bin/python -m unittest test_model_protocol test_model_protocol_execution test_byok_tool_authority test_byok_native_wait test_byok_model -v`

55/55，零跳过，0.643s，退出0；`/tmp/owner-tool-response-ci-fixture-fix.log`。Ruff、diff check通过。没有重跑PG或完整CI；新head仍需独立复审与精确CI，前17项曾漏掉完整协议夹具范围，不称原CI已通过。
