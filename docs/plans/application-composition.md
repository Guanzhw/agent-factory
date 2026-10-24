# 规划：应用服务组合与明确的生命周期归属

状态：Draft 规划；实现与运行验收尚未开始。当前基线 `ab5a98e`，已包含 #98 关闭实现 `5799403`；原问题分析来自 #95。
OpenSpec change：[compose-application-owned-services](../../openspec/changes/compose-application-owned-services/proposal.md)，[设计与真实消费者](../../openspec/changes/compose-application-owned-services/design.md)，[owner 任务板](../../openspec/changes/compose-application-owned-services/tasks.md)。
#97 控制/读取改动待提交后集成，不依赖其未提交实现。

## 问题与结果

平台应能同时安装两个应用，使各自的任务投影、运行控制和关闭逻辑独立工作。现有代码已经隔离核心安装，但科研接入仍依靠替换多个核心服务类和写入 Store 的单一回调。

- `deployment/agent_factory_server/main.py:59-69`：为 API、存储、observer、model dispatch、handoff 等指定科研服务类型。
- `apps/research/agent_factory_research/assembly.py:33-37`：向共享 Store 安装单一运行时回调。
- `platform/agent_factory/store.py:71-73`、`runtime_hooks.py:8-35`：保存并消费这些回调。
- `apps/research/agent_factory_research/services.py:27-38`：通过进程级 `id(store)` 关联查找科研 service graph。

当前装配形态已确认；第二个应用互相覆盖是需要验证的风险，本规划没有将它称为已复现故障。

## 实施范围

1. 逐个追踪现有替换类的真实职责，选出任务投影/控制、运行证据和 lifespan 所需的最少接入点；不把每个旧子类机械转换成公共接口。
2. 让科研应用实例直接拥有并传递自己的 service graph；消费方迁移完成后移除全局关联桥接。
3. 仅对真实多应用消费者组合注册，按明确的 app/runtime 身份派发。重复归属在启动时明确报错；取消发给对应拥有者。
4. 保持通用实现归核心、科研行为归科研。用第二个最小惰性应用夹具证明组合需求，不新增业务应用。

## 验收

- [ ] 完成替换类、回调、graph 消费者的精简清单，并说明每个新增接入点的实际消费者。
- [ ] 新环境安装核心 wheel，连接 PostgreSQL 启动和关闭，科研源码不存在时仍可用。
- [ ] 同一真实服务器安装科研与第二应用，各执行一项确定性任务；取消其中一项不改变另一项的状态与回调。交换安装顺序再验证。
- [ ] 同时运行两个服务器实例，关闭一个不影响另一个，确认不存在跨实例 graph 关联。
- [ ] 运行受影响的 native、科研恢复、远程资源收尾、架构及关闭回归。

Agno 继续拥有执行生命周期，应用回调不能绕开准入或释放未确认资源。本项不引入插件市场、动态热加载、通用依赖注入框架或重写全部 adapter。

## 实施阶段与归属

第一阶段只组合实际多应用消费者：任务投影/控制、运行证据、取消标记与生命周期。按原持久化 plan/adapter/runtime/effect 身份派发；重复归属启动拒绝，缺失或歧义保持 UNKNOWN，不默认交给科研。同任务多个运行资源分别核对，任一未确认仍保留占用。通过真实同服务器双应用任务、交换安装顺序与单项取消验收后，才算第一阶段完成。

第二阶段让科研实例直接持有 graph，通过构造参数与已有 binding factory 闭包传递，迁移全部 19 个 app 文件（含 services 定义）及 7 个脚本后移除进程级关联。不得改成 Store 任意服务字典或另一隐式定位器。通过同进程双服务器隔离、独立核心 wheel 和完整回归后才完成 #99。

#98 核心外层关闭护栏继续统一覆盖所有应用、observer、native 与共享依赖，只有一个整体 35 秒预算，不逐应用重新计时；超时生产进程非零退出，保留原身份及未确认占用。原事务内取消标记仍保持原子性。

root 拥有 composition/core main、规范和最终集成；core-owner 负责精确派发；research-owner 负责科研接入及 graph；scripts-owner 负责七个调用入口；integration-owner 负责双应用/双实例 PostgreSQL fixture。精确文件边界及每项验收见任务板。所有实现任务均未开始，尚无双应用运行通过证据。
