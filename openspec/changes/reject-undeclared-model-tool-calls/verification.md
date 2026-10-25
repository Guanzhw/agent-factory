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
