# Design

## Context

基线9a933aa，云端4CPU/16GiB。沿用相同Node24/Python3.12/uv0.12.1、锁依赖及PostgreSQL17.11镜像；PG固定2CPU/1GiB、loopback端口和默认持久化设置。PR96已有单次full Linux发现、fast/full路由与required集合，不能重复实施。

## Goals / Non-Goals

**Goals:** 逐例和fixture计时；用独立风险证明精简；确定性复现取消与环境失败；同条件前后验收。

**Non-Goals:** 数量配额、无限重试到绿、改变生产超时/停止证明、阶段内混入后续功能、合并/部署与付费调用。

## Decisions

1. 首先使用checkout外观察器包装unittest阶段，逐行落盘；保持原发现顺序、实例与required验证。阶段和嵌套helper时间分别展示，不能重复相加。独立class/module fixture单列，避免将创建2DB/2服务隐藏为测试逻辑成本。
2. 完整基线/最终运行都只有一个重型测试进程；对比相同选择、资源、存储及工具。基线期间不编辑被执行源码，worker只读。原始失败、skips与成功ID保留。
3. 合并以同一风险与行为证据为依据：例如同一已完成task的重放可并入成功旅程；不同权限源、ACK/UNKNOWN分支、真实安装/平台行为仍保留。决策需等待测量，逐项写覆盖映射。
4. MCP先验证排队取消与运行中取消的分界，不把所有取消当停止。授权/DELETE预算失败另作无秘密耗时诊断；不随意删权限检查。
5. Node默认sandbox和获准执行通道采用最小node:test/子进程矩阵；只有实际errno/signal支持才归因环境，独立CLI契约不因环境限制删除。

## Risks / Trade-offs

- 计时包装有开销 → 同观察器前后对照，记录其边界；轻量探针核对原runner语义。
- 单次波动 → 报告失败与环境限制，结合定向确定性验证，不用一次时间判断收益。
- 测试合并隐藏断言 → 保留原行为到新case/子场景对应关系，并独立复审。
- 完整运行中新发现失败 → 保留证据，定向诊断必要环境/产品问题，不假称最终全绿。

## 授权热路径后续

重复SQL从调用图与实际callback计数定位，不能直接删除None/name两个guard边界。仅把一次require_materials_current内最多30明确pins的材料与治理行改成单LEFT JOIN。依赖必须本已出现在allowed pins内，否则仍先拒绝；局部原始行不跨调用保存，hash/immutable/runtime adapter/DFS验证不减少。单次statement的一致读取并非撤回与工具派发互斥，不额外宣称原子授权。

迟到credential结果仍需完整验证，现UNKNOWN不被清除；新增三个短Event反例加入daily Python。批量查询的30pins/下一fresh撤回用例加入daily PG，独立DFS cycle加入daily Python；其余复杂缺失/深度/完整性/adapter测试留完整套件。每日增加的是边界失效检出，不以测试数量下降为目标。

GC诊断只观察，不改变GC开关/阈值或把collect搬到测试前隐藏停顿。首单例基线源码交错污染后明确废弃，冻结root所有权重新测量；保留原数据及测量顺序。单例总耗时未改善，SQL工作减少不等于MCP稳定性修复。
