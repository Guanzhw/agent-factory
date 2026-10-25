## Context
基线551f1bf。首日志 /tmp/af-qa-full-first-windows.log；本地 /tmp/lifecycle-terminal-fixture-before.log，10tests/7errors。旧69d798b Store.completion_context仅查询空ApplicationRuntimeRegistry并返回None；新增budget-only完成支持后读取local_budget_scopes，裸Mock自动生成该属性和completion_context结果，因此进入_finalize_group并在不完整fake task上出现terminal KeyError。

## Goals / Non-Goals
恢复既有竞态测试的无预算语义，保留每项清理/取消/释放顺序断言。不制造预算夹具、不修改生产边界。

## Decisions
显式设置local_budget_scopes=None，匹配Store.__init__默认值。不是添加terminal默认来掩盖进入错误完成路径；真实budget-only原子完成由既有PG专属套件覆盖，本轮不重跑PG/full。

## Risks / Trade-offs
裸Mock的可选服务必须显式配置。此次只修已证实字段，不重写整个测试mock框架。核对旧源码差异，不把旧完整通过泛化到新代码。
