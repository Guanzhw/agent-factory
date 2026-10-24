# Tasks

## 1. Baseline

- [x] 1.1 冻结环境并运行完整适用PG基线，保存阶段/helper耗时、case结果和required门禁；核对原发现ID和计时语义。
- [x] 1.2 输出耗时排序与独立价值审查，明确保留/合并/删除候选和CI已去重边界。

## 2. Failure diagnosis

- [x] 2.1 确定性复现MCP排队/运行中取消差异，实施有证据的必要修复，保留UNKNOWN与撤回检查回归和诊断记录。
- [x] 2.2 用最小矩阵定位Node默认sandbox失败，必要时改善失败诊断并验证CLI契约，不绕过隔离。

## 3. Test simplification

- [x] 3.1 按测量结果实施有限测试/fixture精简，逐项记录原case到保留行为的覆盖关系，并运行受影响定向组。
- [x] 3.2 保留可复用计时入口与使用说明，验证发现/结果/required语义未被观察器改变。

## 4. Integration

- [x] 4.1 串行运行同条件最终完整适用套件和相关静态/Web/核心检查，保存前后比较及剩余失败限制。
- [x] 4.2 独立审查最终diff/覆盖映射与证据，清理自己启动的临时资源，先保留可审阅改动，完成当前阶段结果。

- [x] 4.3 根据补充授权将本阶段独立变更发布为Draft PR并核对精确提交CI；不合并或部署。

## Workflow follow-up

- 当前阶段完成后读取最新远端PR与依赖，分别推进尚未完成的后续功能；不得与本阶段混为一个大改动。

## Coordination

| Owner | Scope | Dependency / state |
|---|---|---|
| coordinator | Core callback integration, profiler/runner, serialized tests, final evidence/CI | Complete serial comparison recorded (after2fail); final fast231pass; exact CI pending |
| MCP worker | Scratch deterministic gate regressions and diagnostic design | Integrated by coordinator; historical authorization-budget cause remains limited |
| suite worker | Three remote/scale/local-driver test files | Implemented; four targeted cases passed |
| Node worker | CLI error/signal diagnostics; independent profiler review | Ten approved architecture cases passed; environment EPERM retained |
| independent reviewer | Callback custody, pruning coverage, remote-handoff diagnosis | No blocking source issue; full failures and timing limits reviewed |

Heavy-test ownership remains coordinator-only. Complete before/after both failed;
remote handoff baseline, after MCP queue wait and ORX pre-POST wait, and historical
DELETE latency remain explicit limits. No timeout/worker-limit change. Owned PG
containers/volumes removed; no live owned fixture server found by scoped scan.

## 持续诊断（未宣称闭合）

- [x] 记录b458028 exact fast/full success与本地失败差异。
- [x] 捕获第二task DELETE原credential迟到时序，新增三分支UNKNOWN反例。
- [x] fresh bounded材料批量读取；5PG+1DFS、原相关30项与12项GC诊断均通过。
- [x] 受控源hash与SQL对照；首交错污染基线保留并排除。
- [ ] 新head精确CI与资源清理。
- [ ] 历史第二任务、ORX gate和remote parent偶发失败的完整共同归因；GC本轮关联不能替代历史根因证据。

## Guardian 回收后续

- [x] coordinator：核对16c861f exact fast/full success，保留历史失败限制。
- [x] history_backend：原Popen独立wait责任与三项纯失败路径验证；只改process_enforcement及专用回归。
- [x] coordinator：串行运行真实guardian回收和既有enforcement验证；原20项中19通过，错误夹具修正后剩余1通过，保留失败。
- [x] history_remote：独立复核退出/UNKNOWN/线程资源边界；补线程启动后中断窗口测试。
- [ ] coordinator：扫描并提交新head，记录精确CI与清理。
