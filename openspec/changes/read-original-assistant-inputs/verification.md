# Verification

基线f25c899；spec先行提交08156ca。范围仅原任务事件输入只读端口、非负订阅深度与安全技术错误码，无schema/main/UI或新执行链。

- 最终便携：`PYTHONPATH=platform:platform/tests python -m unittest test_assistant_events -v`，11通过、0跳过，2.063秒；日志`/tmp/assistant-original-inputs-portable-final-head.log`。使用现有真实SQLite成员/内容和显式预算mock，不把它作为PG预算证明。
- 真实PG目标：`test_assistant_events_postgres.AssistantEventsPostgresTests.test_original_task_input_port_uses_actual_request_and_allocation_binding`，1通过、0跳过，6.551秒；日志`/tmp/assistant-original-inputs-pg-fixed-fixture.log`。真实request/allocation/task绑定与owner隔离、人工无delivery、关联不一致、内容撤回仍需当前读取授权；bridge零调用，未执行模型/GPU。隔离数据库由fixture正常清理。
- PG首失败保留`/tmp/assistant-original-inputs-pg-first.log`：人工任务夹具复用已绑定事件plan，被既有LOCAL_BUDGET_REQUEST_PLAN_CONFLICT正确拒绝；改为原prepare入口生成独立人工plan后通过。没有改产品拒绝、超时或断言。
- 初版规范/code采用大写正则，被独立审查指出任意全大写秘密仍可通过。已改成15项本metadata路径既有Factory code有限集合，其他均仅异常类型；全大写敏感样式与dict.code反例覆盖。旧日志`/tmp/assistant-original-inputs-portable-first.log`不作为最终安全实现证据。
- Ruff三变更Python文件、diff whitespace及OpenSpec strict均通过；未运行full或真实外部服务。
- 独立review已对08156ca之后工作树完整增量给出通过意见；最终精确head复核由coordinator绑定。任务勾选及集成仍归coordinator。
