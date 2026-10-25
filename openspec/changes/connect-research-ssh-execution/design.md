# Design

## Context

基线 `9454000`，本次只读核对，未连接远端。P5 与 D01 的真实目标接线仍缺失，不能把已有接口或合成运行记为完成。

| 已有来源 | 实际能力与缺口 |
| --- | --- |
| `personal_ssh.py:142,264,279`、`ssh_identity.py:74` | owner 资源与短时 ssh-agent 租约；严格 known_hosts、显式 host/port/user，禁代理命令与 agent forwarding。仅 `ssh:prepare`，不是训练 submit/reattach。 |
| `resources.py:28`、`process_provider.py:213` | allocate/inspect/cancel/reclaim 契约与持久 lease；本地 provider 先写原意图，再创建原 custody 并启动。其本地 inode/PID 证明不可当远端证明。 |
| `process_enforcement.py:92,113` | 受界进程/研究进程规格、工作目录及 interpreter 验证；不是集群 scheduler SDK。 |
| `process_runtime.py:268` | 当前同步工具最多观察约 7 秒，未知即报错并保留容量。直接包此工具不能证明长训练的原生暂停/恢复。 |
| `rounds.py:274`、`delegated_operations.py:53` | 固定 root 通过 custody 创建唯一原实验 child；root 已有 native wait 与原操作观察。保留该协议。 |
| `native_bridge.py:206`、`control_commands.py:130` | 普通 Agent 已能以原 tool_call_id continue；受信 external_execution_handlers 可提供结果并复用持久命令。缺 SSH operation 对应的精确等待 handler 与自动观察接线。 |
| `workflow_operations.py:131,155` | custody 接受原 RunContext，不要求调用者一定为 Workflow；已有原 task/run/plan/effect-slot 校验。 |
| `delegation.py:375`、`store.py:301` | child placement 尚不支持；HTTP remote + 本地 scope allocation 明确拒绝。此次不删除这些保护或迁移整个研究 Agent。 |

## Goals / Non-Goals

**Goals:** 保留 root→child→实际训练操作的单一责任链，补显式 SSH 计算目标、可恢复原操作、证据取回与研究消费者接线。透明 TCP 转发只是连接入口，最终 SSH 身份仍严格验证。

**Non-Goals:** 不新增 scheduler、队列、provider while、全局恢复 worker、vault 或新模型 provider；不把 QA 接到训练工具；不自动开防火墙/隧道、生成 key 或安装依赖。SSH 不是 GPU 分配器，不能据连接成功承诺 GPU 独占或集群配额。

## Decisions

### 1. Keep the native experiment child

推荐路线：research root 保持本地；其已有 delegated operation 创建本地 `factory-executor` 实验 child，继承原 scope。child 的显式治理工具将选定训练 CLI 交给 SSH operation，随后通过 `factory_wait_operations` 的原生 external_execution requirement 暂停。操作闭合后原 child/run 收到真实结果，再由既有父 operation 观察 child 终态，root 模型按真实输出评价。

不采用直接让 root 取代实验 child，也不为此新增 child Workflow。新增 Workflow 虽能复用 WorkflowControl，但会另改现实验执行语义；普通 Agent 已有 continuation 与持久命令接缝，先用该最小路线证明。不得将 WorkflowControl 的 step_requirements 直接套给普通 Agent。

### 2. Minimal core seams

- 增加一个受信 SSH process operation adapter，实现已有 `start(context, operation_id, inputs)` / `lookup(context, operation_id)` / `inspect(context, handle)` / `cancel(context, handle)`。它委托 ResourceService 原 lease 与持久 process custody；不建立第二运行状态表/调度器。需增加的 SSH 连接快照与远端原 process receipt 放现 lease/provider body。
- child 治理 launch 工具从不可变 material config 取得显式资源引用和训练规格，模型仅提供声明允许的参数。以原 native tool call 身份确定 effect-slot，经 OperationCustody 持久化后才发 SSH。重复调用或未知回执只读原意图，不给新 UUID 重新提交。
- 抽出既有进程“开始/原结果读取”最窄接口供 adapter 使用，保留原 `ProcessRuntimeService.run` 的现有行为；不放宽其 7 秒界限来维持长连接。远端运行不与 SSH 会话生命周期绑定。
- 给普通 Agent 的 `factory_wait_operations` 注册受信结果 handler：必须核对原 requirement、owner/task/run、原 operation ID 集合与闭合证据，只返回这些 operation 的结果。模型不得用他人的 ID/伪结果继续原 run。
- 在既有 lifecycle/RuntimeRegistry.observe_waits 遍历中观察这一精确工具消费者，闭合后提交由原 requirement 派生的唯一 ControlCommands 命令，继续原 NativeBridge；无新轮询器。这里 approved 字段是既有工具结果提交协议，不新增逐轮人工审批或代替用户权限。必须验证原授权、预算、取消和命令回执；UNKNOWN 不提交结果，不自动重发 continue。

这些是待实现接缝，不是基线现成能力。先做实际普通 child pause→控制器重启→同 run 恢复的否证测试，再扩研究消费者；若现 ControlCommands 的精确身份/恢复边界不满足，报告具体缺口并独立审查最小修改，不能偷偷回退第二控制器。

### 3. SSH identity and remote execution boundary

资源保存转发入口 `host:port`、最终 SSH username、最终主机公钥与允许的远端根目录，沿现 vault credentialRef/revision 和短时 agent lease。透明四层 TCP 转发不需要 ProxyJump；严格校验仍针对最终主机，不能信任中间服务器 key 或关闭校验。HTTP 代理、交互式跳板和命令级网关不是已证明兼容的透明映射。

首次能力切片仅定义直接受界进程后端的受控 loopback SSH 验证。真实集群是否允许直接运行尚待用户提供事实；若必须 scheduler 提交，先选择其真实已安装适配契约，不用 shell 在登录节点启动训练冒充调度分配，不预选 Slurm。

远端必须有明确可用的匹配版本进程 helper/interpreter。只读检查其版本、原始身份存储与必要隔离能力；本变更不自动安装 runtime。通过 SSH 发有限 JSON 命令，参数不拼接成任意 shell；远端 helper 复用 BoundedProcessAdapter 的原 custody 与停止证明，不提供独立调度服务。helper 安装路径、启动契约在实施前冻结，由受控夹具验证；不能声称当前已有生产 SDK。

远端 custody 绑定原 owner/task/run/operation/lease、选定 endpoint/hostkey/root、进程启动身份。断线不是停止，SSH退出码不等于训练退出码。提交已发送但应答丢失时，原 journal 的存在/缺失必须以同身份查询；无可证实“从未开始”记录则 UNKNOWN，不重新 launch。连接改变/凭据撤回后不新提交；只允许现机制授权的原身份观察/取消，不能新建旁路凭据，无法观察则继续 UNKNOWN/hold。

### 4. Research placement, budget and evidence

研究 setup/已确认约定显式选择 SSH 计算资源及可用训练材料。该 placement 指计算位置，不是 root/child native queue 的迁移。对应材料精确绑定 SSH adapter/连接及可用参数 schema，旧未确认目标不能默默选默认远端。配置变更走现 goal revision/确认，不重置项目 scope。每轮与 child 复用原预算；ResourceService 单独约束实际 CPU/内存/磁盘/时限/GPU 资源声明，SSH检查不扩大预算。

实际 stdout/stderr、退出码、选定指标和明确文件清单从原运行目录取回，经现 artifact_write 与研究精选证据契约归档；完整原结果保持 owner 私有，团队仅按现 sourceContentIds/精选字段与附件授权读取。拒绝越根路径、symlink 替换、跨运行文件和尺寸越界；先确认完整归档，再允许独立的显式清理，不把 reclaim 等同删除用户代码/数据。科学负结果保留；进程成功不自动代表目标达成。

### 5. Validation and delivery

先 portable 合同与原身份负例，再单个隔离 PG + 本机真实 sshd/透明 TCP 转发测试。实际运行一个受控短 CLI，覆盖失联、原生 child 暂停、硬重启、取消和文件回收；不使用真实 key/provider/GPU。保留首失败，重 PG 串行。随后实际研究 workflow 观察真实工具结果进行模型决策的确定性替身测试；它只证明协议，不替代正式模型 C 层。D01 仍需目标机、真实训练与允许的故障实验，未具备标 BLOCKED。

## Risks / Trade-offs

- 现 Agent external handler 原用于确认路径 → 实测自动原结果递交是否只继续原 run，检查重复命令、foreign requirement、父取消；不复制恢复逻辑。
- 远端 helper 缺失或隔离不满足 → 明确不可执行并保留配置，不自动安装/降级/假装GPU隔离。
- 转发断开或主机替换 → 按 pinned hostkey 拒绝/UNKNOWN，不重派；不由本项目管理代理基础设施。
- 实际集群只允许 scheduler → 生产路径保持 BLOCKED，追加真实 scheduler 适配规范，不把直接后端当已适配。

## Migration Plan

以显式新 adapter/material version 发布，不改旧 immutable plan。依赖并行去 demo 变更的正式认证和测试夹具；无数据库清空/凭据迁移。回滚停用新提交但保留原 adapter 的 inspect/cancel 能力与未决 custody；不能卸载原代码后声称已清理远端任务。

## Required target facts

正式运行前最少需要：Factory 可达的映射入口 host/port；最终 SSH 用户/主机公钥及已存在连接引用；允许工作目录；是允许直接运行还是必须经某个已安装调度器（名称及正常提交/查询/取消方式）；可用 Python/runtime 与训练入口/环境/数据位置；GPU资源分配方式与本次运行时限/预算、是否允许断线/取消验证。只要配置引用与非秘密元数据，不在聊天索要私钥。受控本机测试可先行，不能据此补写未知目标事实。
