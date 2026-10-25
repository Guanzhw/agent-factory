# Design

## Context

TextTestRunner正常返回后已有postgres_acceptance summary。复用该数据，不新建报告框架。

## Decisions

增加可选--summary-file，只在run_checks返回后写JSON；补selected/failures/errors/shouldStop，accepted明确拒绝shouldStop。CI运行前删除本次目标旧回执以免重用，runner写到RUNNER_TEMP独立路径。后续always/full step验证JSON存在、suite正确且accepted为true，独立短输出及step summary；原长日志保留。

不以selected==testsRun拒绝合法class/module skip，不新增hash或提交字段（job已绑定head）。测试用临时文件和小型unittest fixture，无需PG或全量重跑。

## Risks / Trade-offs

该回执证明正常runner完成及既有required规则，不证明真实外部供应商。旧CI缺失计数仍未核实；新增门槛只约束后续运行。
