# Design

## Context

基线 `ab5a98e`，包含 #98 `5799403`；阶段一实现已进入定向验收。动机见 proposal。#97 `965350f`已集成，不引用未提交接口。

实际消费者清单：

| 现有接入 | 消费者及责任 | 组合决定 |
| --- | --- | --- |
| Store 四个 `runtime_*` 回调 | `runtime_hooks.py` 的 effect held、ended reason、cancel；`Store.request_cancel` 的事务内标记 | 按原 task/runtime/effect 身份选择拥有者，多个真实资源分别核对 |
| `ResearchFactoryAPI` / `ResearchControlCommands` | 详情证据、等待控制、原 requirement 结果 | 按持久计划及执行绑定派发；读取/控制边界遵循 #97 提交后的契约 |
| `ResearchLifecycleObserver` | inference wait 核对和事务内取消标记 | 应用观察由原 observer 驱动，不新增执行循环 |
| `ResearchDelegatingModel` | 推理暂停、恢复及开发模型失败防重放 | 保留科研行为；只有实际共用消费者才抽取接口 |
| policy/storage/connections 兼容类 | 科研授权、证据保留、原连接 reclaim | 不机械转成公共 hook，逐项验证第二应用不会被科研默认覆盖 |
| handoff 双兼容类与 delegation | 科学 placement、原 receipt 校验、原委托取消 | 按持久 placement/runtime 身份派发，不能使用安装顺序 |
| `research_lifespan` / shutdown | 原 controller、executions、晚生 cleanup 及 graph | composition 显式组合，#98 核心护栏统一拥有整体期限 |
| 其他单值接入 | application environments、SSH package/probe、delegated root validator、scientific service | 明确唯一拥有者并拒绝冲突，不因只改四个回调就宣称完成 |

`services_for()` 当前生产消费者共 26 文件（含 services 定义）：19 个 app 文件、7 个 scripts，具体清单见 tasks。已有 `ExecutionBindings.register(kind, adapter_id, revision, factory)` 拒绝重复，可复用捕获应用实例的工厂。

## Goals / Non-Goals

**Goals:** 两阶段完成静态双应用组合和 graph 实例归属；核心不导入具体 app；仍由 Agno 管理执行。

**Non-Goals:** 插件市场、热加载、通用 DI/service locator、新业务应用、重写全部 adapter、新授权体系；本项不部署、不合并、不调用付费或真实模型服务。

## Decisions

1. 精确派发复用持久 plan/adapter/runtime/effect 身份。旧计划采用已存在不可变绑定的确定性映射，歧义或缺失不默认科研、不重派发。任意匹配谓词或最后安装者获胜不能保证顺序无关。
2. 只注册真实多应用消费者；证据按拥有者合并，任一未确认资源仍 held。取消通知不是 stop proof。保持取消标记与核心状态在同一事务，避免改成异步通知产生中间状态。
3. 应用实例直接持有 `ResearchServices`，通过构造参数和 adapter factory closure 传递。复用原 `BindingContext`；不将全局表换成 Store 任意服务字典或 ContextVar 隐式定位。
4. core 外层 lifespan 的 #98 墙钟护栏覆盖全部应用、observer、native 和共享依赖。各应用使用同一剩余期限，关闭逆序、不重新开始 35 秒计时；未完成进入原部署非返回 fatal 策略。
5. 第二应用仅为验收夹具，必须实际经原生 runtime 执行任务；两个独立单应用服务器不能替代同服务器组合验收。

## Risks / Trade-offs

- 绑定工厂先于当前 install 创建 → graph 可先构造，但开始执行前必须完成依赖安装；失败按已获得依赖逆序清理。
- 旧计划无统一 app 标识 → 从现有不可变绑定映射并覆盖旧数据测试，不贸然添加新必填持久字段。
- task 同时拥有多个 effect → 按原 effect/runtime 分别核对，不能只调用一个 task owner 后释放全部容量。
- #97 修改相同详情、控制、handoff 文件 → 等待已提交接口，root 串行解决冲突并复跑读取无副作用回归。
- 阶段一仍有 graph 桥接 → 明确中间状态；阶段二全部迁移并删除桥接后才满足 #99 完整范围。
- Python Timer 不是硬实时保证 → 沿用 #98 已记录的持 GIL C 扩展限制，不扩大退出保证。

## Migration Plan

阶段一先交付精确注册/派发和显式生命周期组合，通过真实双应用、双安装顺序验收。阶段二迁移 graph 消费者及脚本，删除全局关联，通过同进程双服务器隔离和完整关闭回归。每阶段保留现有 HTTP、原 effect/intent/lease 身份；无计划中的数据库迁移。失败回退代码变更，保留已有原操作记录，不重新派发。未完成静态、真实 PostgreSQL、独立 wheel 验收前不标记完成。


## Stage-one implementation

`ApplicationRuntimeRegistry`按精确(kind,adapterId,revision)和原run effect key映射，已知legacy仅在无modern绑定时适用。成员自发发布的applicationRef不需要管理员注册，不引入新的准入门槛。显式声明但hooks缺席保持UNKNOWN/held；所有声明完全丢失的未知历史binding无法凭空推断owner，原未完成effect规则仍保留。空registry不额外读取任务/plan。

`ApplicationAssembly`静态安装、上下文、释放与abort组合，重复owner及独占写入槽位启动前拒绝；普通资源消费者无需claim。应用constructor/abort必须同步、无运行派发、无无界清理；禁止async callable静默漏await。生产原shutdown guard为唯一35s计时，core发布幂等begin_shutdown；组合在部分startup失败的stack退出之前也调用它。关闭顺序保留app→observer/native→共享依赖→graph release。

多个独立app取消即使一个失败也尝试其余原owner后传播；原外层workflow收尾保持成功前置，不以未知app清理当成功继续。没有改动原stop/UNKNOWN释放规则。
