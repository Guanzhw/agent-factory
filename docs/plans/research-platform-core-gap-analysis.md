# 新研究应用：底座能力与缺口

2026-10-25，只读源码分析与规划，不是新增能力的验收记录。需求依据 [CONTEXT](../../CONTEXT.md)，责任决定见 [ADR 0002](../decisions/0002-core-communication-research-assistant-boundary.md)，实施顺序见 [交付规划](research-platform-delivery-plan.md)。

## 分析基线与证据范围

本地文档分支继承 PR104 的 `ddc82b2642e8784099e5590040ef7d4223df18b1`；运行代码、测试和工作流与 `506cb4eff8aa96bfa53c13e8fe57beb65adeb5ab` 相同。[PR104](https://github.com/Guanzhw/agent-factory/pull/104) 在本轮交接中仍为 Draft、未合并，不能将其能力写成 main 已有状态。以下源码路径均相对此基线；本轮没有重新执行产品测试或读取真实凭据。

既有 [验收报告](../../openspec/changes/remove-research-verify-core/verification.md) 与 [full CI](https://github.com/Guanzhw/agent-factory/actions/runs/40171164057) 是代码基线证据：PG 1815 项中 1810 通过、5 跳过；Windows 1815 项中 1079 通过、736 跳过，Web 431 项。独立 core wheel、空数据库生命周期、浏览器 demo 和生产模式下本地合成身份路径已验收。它们不证明真实组织身份、真实模型、真实个人 GPU 或新研究旅程。历史 MCP/remote 时序偶发失败根因仍未完全闭合；没有整套测试加速结论。

## 能力核对

下表的“缺口”来自对当前注册入口及相关实现的核对，不是仅按名称猜测；“复用”也不表示新需求无需适配。

| 需求 | 当前源码与实际职责 | 新需求差距及边界 |
| --- | --- | --- |
| 无研究应用也能运行 | [架构映射](../../scripts/architecture-python.json)、[部署装配](../../deployment/agent_factory_server/application_composition.py) `ApplicationAssembly`、[前端装配](../../web/composition.tsx)：默认应用列表为空，显式注册生命周期 | 新应用必须可选择安装；移除其包、路由和种子后登录、主页、通用资源仍可用。不能把助手注册作为 core 启动前提 |
| 成员与资源身份 | [AuthService](../../platform/agent_factory/auth.py)、[ConnectionService](../../platform/agent_factory/connections.py)、[EncryptedCredentialVault](../../platform/agent_factory/credential_vault.py)、[PersonalModels](../../platform/agent_factory/personal_models.py) | 复用成员认证、模型配置和凭据托管；缺少独立于单次任务、归属某成员和应用的稳定助手端点。不要建第二套账户/vault |
| 应用调用端口 | [ApplicationIdentity / ApplicationLifecycle](../../platform/agent_factory/application_interface.py)、[ApplicationRuns](../../platform/agent_factory/application_runs.py) | 已有 start/request/query/cancel/events/artifacts，requestId 绑定原始提交；identity 是 owner/task/run/app/version，不是个人长期助手身份。pause/continue 不在必需公共端口中 |
| 执行与恢复 | [NativeBridge](../../platform/agent_factory/native_bridge.py)、[ApplicationRuntimeRegistry](../../platform/agent_factory/application_runtime.py)、[原生 workflow](../../platform/agent_factory/native_workflows.py) | Agno/native queue 唯一拥有任务执行；task 对应 native session。Registry 的 RuntimeOwner 管应用生命周期，不是成员助手。长期助手需关联多次有界 task，不能把不同任务强塞进同一 task 身份 |
| 临时实验 agent | [DelegationService](../../platform/agent_factory/delegation.py) | 已有独立 native child、预算收窄、级联取消和 UNKNOWN 保留。需应用定义实验职责与结果关联；parent 完成不等于 child 已停止，不另造子执行器 |
| 多轮预算 | [LocalBudgetScopes](../../platform/agent_factory/local_budget_scopes.py)、[UsageLedger](../../platform/agent_factory/usage_ledger.py) | 已有 owner scope、幂等分配、原 task/plan 绑定、未知用量保留。应用需将项目与目标版本关联到预算承诺；不是跨成员共同钱包。BYOK/unmetered 不能虚称精确金额硬上限 |
| 消息、离线问答 | [CompositionInboxService](../../platform/agent_factory/composition_inbox.py)、[EventReplay](../../platform/agent_factory/event_replay.py)、[SchedulingService](../../platform/agent_factory/scheduling.py) | inbox 是 owner 的组合提案；event replay 是 task 事件分页；schedule 是持久定时准入。三者都不是现成 A2A mailbox、订阅交付或离线助手唤醒。需最小通用消息及触发准入契约，复用 native queue |
| 团队记录 | [ResourceSharing](../../platform/agent_factory/resource_sharing.py)、[Store](../../platform/agent_factory/store.py) artifact 接口 | 现有个人/团队资源共享不等于任意研究记录 ACL；任务与产物读取按 owner 隔离。应用定义可共享记录及默认策略，调用 core 权限机制。Bob 读 Alice 的已共享证据不能变成 Bob 可读 Alice 所有 jobs 或凭据 |
| 证据真实性 | [FactoryApplicationContext](../../platform/agent_factory/_application_context.py) | 写产物会重查原 run 权限，默认 `application_output` / `unverified`。生成文字、进程成功、科学结论分别处理；应用必须给出指标、条件和出处，不能让模型自行将生成文本标为已验证 |
| 个人远端 GPU | [RemoteExecution](../../platform/agent_factory/remote_execution.py)、[remote handoff](../../platform/agent_factory/remote_handoff.py)、[ProcessRuntimeService](../../platform/agent_factory/process_runtime.py)、[PersistentResourceService](../../platform/agent_factory/resources.py)、[GpuBinding](../../platform/agent_factory/gpu_custody.py) | 已有原身份 handoff、receipt、进程与租约观察、GPU custody；不等于已完成个人 GPU 的驱动/训练环境、数据同步和真实验收。GPU binding 明示非硬件配额/设备隔离，不能排除 Factory 外部进程 |
| 证据留存 | [StorageGovernance](../../platform/agent_factory/storage_governance.py) | 已有磁盘准入、归属目录、隔离区和保留约束；不是物理磁盘 quota sandbox。应用需明确研究证据保留策略、导出和远端清理前归档；不可直接复用工具的默认自动清理策略 |

## 可复用的已有回归锚点

- [application interface PG](../../platform/tests/test_application_interface_postgres.py)：v1/v2 原任务、丢响应后 request 查询、重启 owner 隔离、public context 产物。
- [local budget scopes PG](../../platform/tests/test_local_budget_scopes_postgres.py)：重复和并发分配、一次结算、UNKNOWN hold、task/plan 不可重绑、deadline 和 BYOK 边界。
- [remote v2 PG](../../platform/tests/test_remote_v2_integration_postgres.py)：真实本地进程/协议组合、丢回复后原身份恢复、取消及正向停止证据；不是实际个人 GPU 训练。
- [reusable tool PG](../../platform/tests/test_reusable_tool_operations_postgres.py)：同一材料与不同成员连接、共享撤回、CLI lost-ack。不能将 installed adapter 的成功扩大为任何新工具已验收。
- [独立核心安装检查](../../scripts/check_core_install.py)、[架构检查](../../scripts/check_architecture.py)：包隔离、真实生命周期与依赖方向；不能替代浏览器和运行时权限测试。

新用例应检验这些边界的新组合与新增状态，不为测试数量复制已有断言。出现同类 MCP/remote 时序失败时，保留首次失败及任务/线程/清理时间线，不用放宽超时或重复整套追绿覆盖历史问题。

## 最小新增范围

核心新增的是可由非研究应用使用的助手端点、带关联的可靠消息和事件触发，以及受现有成员/资源权限约束的内容读取接入。研究项目、目标修订、实验记录、科学解释、选择同事的相关性和何时结束研究，均不进入 core schema 或策略。具体数据表/API 仍须在实施时以两个简单非研究端点证明通用性；不因“未来可复用”建立通用分布式平台。

所有新消息引起的执行仍经已有准入、预算、native task 和原操作恢复；消息收到、任务接纳、任务完成、外部副作用停止是不同事实。应用可重建研究视图，不能因视图缺失或消息重投重新提交未知原操作。
