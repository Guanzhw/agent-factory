# Verification

基线30699a3，规范先行c6eda03。修改仅研究Workflow JSON文本指令和专属测试；core模型/guard不改。原浏览器失败由集成任务保存，本单元不复制真实请求日志。

- 真实OwnerChatModel + httpx.MockTransport + NativeWorkflows/WorkflowDecisionModel包装：新增应用测试加原Workflow测试首轮6/6，0.370s，`/tmp/research-json-text-portable-first.log`。
- 新增撤销凭据反例的第一次运行7项中1失败，`/tmp/research-json-text-portable-final.log`：测试错误地期待Agent.arun抛ModelProviderError；实际Agno返回status=ERROR且HTTP零调用。修正为严格检查ERROR、固定安全错误码、一次凭据查询、零HTTP/child/决定，未修改产品行为。
- 最终命令 `PYTHONPATH=platform:platform/tests:applications:applications/tests /workspace/agent-factory-research-next/.venv/bin/python -m unittest test_research_owner_model test_research_workflow -v`：7/7通过，0跳过，0.229s，exit0，`/tmp/research-json-text-portable-corrected.log`。
- Ruff两文件和git diff --check：exit0。
- Pyright针对workflow.py，临时配置相对include及当前platform/applications、既有venv：0 errors/0 warnings，exit0，`/tmp/research-json-text-pyright.log`，配置`/tmp/research-json-pyright.json`。进程已结束。

测试真实执行文本adapter及Agno模型/函数包装；一个实际Workflow.arun stop完整路径COMPLETED且零child。其余决策/评价直接执行同一已注册Agent及被原生包装的函数边界；非法JSON/围栏/缺字段/额外字段/无证据达标零child、零额外模型调用，无效评价只保留原child调用且零最终决定。wire无response_format、原选定model不变；合成凭据当前检查和原治理tool-budget拒绝均生效。

所有HTTP为synthetic transport，authority/预算存储ports为受控fixture，不能冒充生产vault/PG/真实模型或科学自主验收。本单元未运行PG；集成端应以新Workflow pin重建公开应用版本再复验实际完整研究路径，不修改历史immutable plan。

作者外精确head审查待集成负责人确认，tasks由coordinator勾选。
