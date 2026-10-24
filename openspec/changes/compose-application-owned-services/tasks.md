# Tasks

状态：阶段一已实现并定向验证，阶段二待继续。root 维护规范、接口集成与验收勾选；实施与独立审查使用不同上下文。重型测试和 PostgreSQL 由 root 串行运行。文件分组是后续派发约定，不表示人员已开始实现。

## 1. 第一阶段：明确归属和双应用组合

- [x] 1.1 root：集成 #97 已提交的控制/读取契约，记录确定提交及差异；验证不引用未提交代码，相关读取无副作用回归通过。
- [x] 1.2 core-owner（依赖 1.1）：实现任务/runtime/effect 精确注册及派发，保留事务内取消标记；新增重复归属、旧绑定映射、缺失 owner 保持 UNKNOWN、多 effect 未确认不释放的便携测试，更新 design 的最终接口。
- [x] 1.3 research-owner（依赖 1.2）：将科研详情/控制/observer 接入明确拥有者；验证无关第二应用不会触发科研处理，原 inference wait 原子取消和科研恢复回归通过。
- [x] 1.4 root（依赖 1.3）：显式组合应用生命周期和其余实际共享单值接入，重复拥有者拒绝；验证所有 app、observer、native、共享依赖只使用一个整体 35 秒预算，复跑 #98 正常/超时真实退出测试。
- [x] 1.5 integration-owner（依赖 1.4）：新增惰性第二应用 fixture 和真实 PostgreSQL/HTTP 测试；在同一服务器运行两应用任务、交换安装顺序、取消其中一个，验证另一任务状态与回调不变，并记录结果。此项通过仅完成阶段一。

## 2. 第二阶段：应用实例拥有服务图

- [ ] 2.1 research-owner（依赖阶段一）：由科研实例持有 graph，通过构造参数和绑定工厂闭包传递，迁移下列 app 消费者；逐批补直接注入与原任务身份回归，验证安装前不得执行半初始化服务，更新装配说明。
- [ ] 2.2 scripts-owner（依赖 2.1）：迁移下列七个脚本使用显式应用实例或返回的 graph；运行对应合成 assembly/preset 检查并记录入口调用方式，不运行真实模型。
- [ ] 2.3 research-owner（依赖 2.2）：删除 `_services`、`services_for`、`release_services` 及剩余生产桥接；用源码搜索和实例隔离测试验证没有改成另一个隐式服务定位器。
- [ ] 2.4 integration-owner（依赖 2.3）：新增同进程双服务器真实生命周期测试，关闭一个后另一实例继续控制原任务；同时验证构造失败清理与 #98 pending cleanup 依赖归属，记录实测结果。

## 3. 集成验收

- [ ] 3.1 root：构建核心 wheel，在无科研源码的新环境连接 PostgreSQL 启动、健康检查并关闭；运行架构直接/间接违规夹具、`npm run check` 和相关依赖审计，记录实际结果。
- [ ] 3.2 independent-reviewer：只读复核精确派发、双实例隔离、UNKNOWN 不重放、单整体期限与文件边界；root 复跑受影响 native、科研恢复、远程收尾、#97 读取与 #98 退出回归后勾选，未验证外部服务继续明确标注。

## Ownership

| owner | 精确文件范围 |
| --- | --- |
| root | `platform/agent_factory/main.py`；`deployment/agent_factory_server/main.py`、`shutdown.py`；本变更规范、`docs/plans/application-composition.md`、架构 maps 和 CI 配置；既有 #98 进程验收测试由 root 串行集成 |
| core-owner | `platform/agent_factory/runtime_hooks.py`、`store.py`、`factory_api.py`、`control_commands.py`、`lifecycle_observer.py`；必要时新增 `application_runtime.py`；对应新 `platform/tests/test_application_runtime.py`；既有相关 core 回归夹具 |
| research-owner | 下列 app graph 文件；`factory_compatibility.py`、`lifecycle_compatibility.py`；按实际共享需要迁移 `connections_compatibility.py`、`delegation_compatibility.py`、`handoff_compatibility.py`、`model_compatibility.py`、`storage_compatibility.py`，不得机械新增 hook；对应 app-only 测试与 `test_application_assembly.py` |
| scripts-owner | 下列七个 scripts；对应 `test_autoresearch_scientific_assembly.py`、`test_research_candidate_assembly.py`、`test_autoresearch_operator_bindings.py`（新增文件仅在确需时） |
| integration-owner | 新 `apps/research/tests/python/test_application_composition_postgres.py`、`application_composition_fixture.py`；`test_application_assembly_postgres.py` |
| independent-reviewer | 只读最终 diff 和验证回执，不修改实施文件 |

app graph 文件均位于 `apps/research/agent_factory_research/`：`assembly.py`、`services.py`、`autoresearch.py`、`autoresearch_children.py`、`autoresearch_custody.py`、`autoresearch_profile.py`、`autoresearch_remote_children.py`、`autoresearch_scientific_child.py`、`autoresearch_session_control.py`、`comparison_profile.py`、`control_compatibility.py`、`policy_compatibility.py`、`remote_scientific_origin.py`、`remote_scientific_profile.py`、`remote_scientific_receiver.py`、`research_bootstrap_assembly.py`、`research_bootstrap_controller.py`、`research_runtime_hooks.py`、`synthesis_runtime.py`。

七个 scripts：`run_research_baseline.py`、`research_candidate_assembly.py`、`autoresearch_operator_bindings.py`、`research_candidate_state.py`、`run_research_candidate.py`、`autoresearch_scientific_assembly.py`、`autoresearch_scientific_preset.py`，均位于 `scripts/`。

共享文件变更由 root 重分配后串行实施；不扩大某 worker 对整个目录的权限。新增接口必须对应 design 中实际消费者。

## Workflow follow-up

- root 在实现及验证完成后更新 Draft PR；禁止自动合并、部署、付费或真实模型调用。
