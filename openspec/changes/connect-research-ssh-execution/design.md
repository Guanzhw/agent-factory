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
| `application_runtime.py:36,231,237` | observe_waits 仅遍历原 plan 匹配的 owner；control 进一步按工具的精确 adapter/revision 选 owner，不能只注册一个无人选中的 callback。 |
| `application_runs.py:20`、`research/evidence.py:67` | tool_results 仅支持唯一 MemberToolOperation CLI binding 和原 personal-tool DONE receipts。SSH 多工具等待链不满足该契约，必须新增窄读口，不能伪装 CLI 回执。 |
| `workflow_operations.py:131,155` | custody 接受原 RunContext，不要求调用者一定为 Workflow；已有原 task/run/plan/effect-slot 校验。 |
| `delegation.py:375`、`store.py:301` | child placement 尚不支持；HTTP remote + 本地 scope allocation 明确拒绝。此次不删除这些保护或迁移整个研究 Agent。 |

## Goals / Non-Goals

**Goals:** 保留 root→child→实际训练操作的单一责任链，补显式 SSH 计算目标、可恢复原操作、证据取回与研究消费者接线。透明 TCP 转发只是连接入口，最终 SSH 身份仍严格验证。

**Non-Goals:** 不新增 scheduler、队列、provider while、全局恢复 worker、vault 或新模型 provider；不把 QA 接到训练工具；不自动开防火墙/隧道、生成 key 或安装依赖。SSH 不是 GPU 分配器，不能据连接成功承诺 GPU 独占或集群配额。

## Decisions

### 1. Keep the native experiment child

推荐路线：research root 保持本地；其已有 delegated operation 创建本地 `factory-executor` 实验 child，继承原 scope。child 的显式治理工具将选定训练 CLI 交给 SSH operation，随后通过 `factory_wait_ssh_process` 的原生 external_execution requirement 暂停。操作闭合后原 child/run 收到真实结果，再由既有父 operation 观察 child 终态，root 模型按真实输出评价。

不采用直接让 root 取代实验 child，也不为此新增 child Workflow。新增 Workflow 虽能复用 WorkflowControl，但会另改现实验执行语义；普通 Agent 已有 continuation 与持久命令接缝，先用该最小路线证明。不得将 WorkflowControl 的 step_requirements 直接套给普通 Agent。

### 2. Minimal core seams

- 增加一个受信 SSH process operation adapter，实现已有 `start(context, operation_id, inputs)` / `lookup(context, operation_id)` / `inspect(context, handle)` / `cancel(context, handle)`。它委托 ResourceService 原 lease 与持久 process custody；不建立第二运行状态表/调度器。需增加的 SSH 连接快照与远端原 process receipt 放现 lease/provider body。
- child 治理 launch 工具从不可变 material config 取得显式资源引用和训练规格，模型仅提供声明允许的参数。以原 native tool call 身份确定 effect-slot，经 OperationCustody 持久化后才发 SSH。重复调用或未知回执只读原意图，不给新 UUID 重新提交。
- 抽出既有进程“开始/原结果读取”最窄接口供 adapter 使用，保留原 `ProcessRuntimeService.run` 的现有行为；不放宽其 7 秒界限来维持长连接。远端运行不与 SSH 会话生命周期绑定。
- SSH child 精确工具 registrations 为 launch adapter 与专用 wait adapter（例 `ssh-process-launch-v1@1`、`ssh-process-wait-v1@1`），wait factory 复制现 `factory_wait_operations` 的原生 Function，仅将 name 设为 `factory_wait_ssh_process`；不变更原 Function，不提供旧名兼容别名。通过 RuntimeRegistry.register 的 exact `bindings=(('tool', adapterId, revision), ...)` 同时绑定到唯一 `core-ssh-process` owner；配置指纹仍由不可变 bindings/custody 校验。其 hooks 提供 observe_waits 和 external_result。Research root 的 `research-wait-operations-v1` binding 和 research nativeComponent owner 保持不变，SSH hook 不接管父 root 的 delegated-child等待或研究finalizer。不用全局未限定 handler 抢占所有同名 wait。
- 普通 Agent 的 external_result hook 必须核对原 requirement、owner/task/run、原 operation ID 集合与闭合证据，只返回这些 operation 的结果。调用方沿既有 registry.control 的精确 wait binding 选择 owner，模型不得用他人的 ID/伪结果继续原 run。
- 现 lifecycle/RuntimeRegistry.observe_waits 只对匹配 SSH binding 的 child 自动收尾。命令 ID 由原 child/run/requirement/tool_call_id及原 requirement version 派生；先查询原 ControlCommands receipt，已有 PREPARED/DISPATCHING/已确认回执走原命令处理/只读恢复，不能重新读新 version 改ID重新提交。无记录才检查当前精确 requirement 并创建一次命令。继续原 NativeBridge，无新轮询器。approved 字段是既有工具结果提交协议，不新增逐轮人工审批或代替用户权限。UNKNOWN 不提交结果；continue 可能已发送但 ACK 丢失后必须核对原 queue/native metadata command proof，不重发、不新建 run。

这些是待实现接缝，不是基线现成能力。先做实际普通 child pause→控制器重启→同 run 恢复的否证测试，再扩研究消费者；若现 ControlCommands 的精确身份/恢复边界不满足，报告具体缺口并独立审查最小修改，不能偷偷回退第二控制器。

### 3. SSH identity and remote execution boundary

资源保存转发入口 `host:port`、最终 SSH username、最终主机公钥与允许的远端根目录，沿现 vault credentialRef/revision 和短时 agent lease。透明四层 TCP 转发不需要 ProxyJump；严格校验仍针对最终主机，不能信任中间服务器 key 或关闭校验。HTTP 代理、交互式跳板和命令级网关不是已证明兼容的透明映射。

首次能力切片仅定义直接受界进程后端的受控 loopback SSH 验证。真实集群是否允许直接运行尚待用户提供事实；若必须 scheduler 提交，先选择其真实已安装适配契约，不用 shell 在登录节点启动训练冒充调度分配，不预选 Slurm。

远端必须有明确可用的匹配版本进程 helper/interpreter。只读检查其版本、原始身份存储与必要隔离能力；本变更不自动安装 runtime。通过 SSH 发有限 JSON 命令，参数不拼接成任意 shell；远端 helper 复用 BoundedProcessAdapter 的原 custody 与停止证明，不提供独立调度服务。helper 安装路径、启动契约在实施前冻结，由受控夹具验证；不能声称当前已有生产 SDK。

ResourceService lease、准入、总额度与 PostgreSQL 记账始终留在 Factory；不把依赖本地 Store、root lock、资源池 SQL 的 ProcessResourceProvider 搬到远端。SSH adapter 在 Factory 侧实现现 provider 契约，将原身份请求交给远端有限 helper；远端仅运行 BoundedProcessAdapter 的本地 journal、原进程身份核对与停止动作，不保存第二份全局资源池/任务队列，也不主动启动恢复循环。

远端 custody 绑定原 owner/task/run/operation/lease、选定 endpoint/hostkey/root、进程启动身份。断线不是停止，SSH退出码不等于训练退出码。提交已发送但应答丢失时，原 journal 的存在/缺失必须以同身份查询；无可证实“从未开始”记录则 UNKNOWN，不重新 launch。连接改变/凭据撤回后不新提交；只允许现机制授权的原身份观察/取消，不能新建旁路凭据，无法观察则继续 UNKNOWN/hold。

### 4. Research placement, budget and evidence

研究 setup/已确认约定显式选择 SSH 计算资源及可用训练材料。该 placement 指计算位置，不是 root/child native queue 的迁移。对应材料精确绑定 SSH adapter/连接及可用参数 schema，旧未确认目标不能默默选默认远端。配置变更走现 goal revision/确认，不重置项目 scope。每轮与 child 复用原预算；ResourceService 对 CPU/内存/磁盘/时限/GPU 资源声明作准入核对，实际远端强制执行另凭能力和证据确认；SSH检查不扩大预算。

### 4a. Frozen first-slice protocol

固定协议 `factory-ssh-process-v1`，operation adapter `ssh-process-operation-v1` revision `1`，空静态adapter配置的指纹沿现digest({})；每个operation实际target/config已包含在原inputs与lease，不能用此固定pin替代目标身份。工具adapter `ssh-process-launch-v1@1`（toolName `ssh_process_launch`）与 `ssh-process-wait-v1@1`（toolName `factory_wait_ssh_process`）归唯一owner `core-ssh-process`。等待hooks签名 `SSHOperationWaits(store, custody, operation_pin, *, commands)`，由composition显式将两个exact tool bindings注册一次；commands显式注入现factory_api.commands，不经Store私有服务绕行。pin及tool binding常量由新增`ssh_process_contract.py`集中提供。它不负责新提交、选目标或研究finalizer，也不再装配第二cleanup链；现runtime_hooks已调用同store.workflow的task_held/cancel_task。

应用/模型可见launch参数只含已声明训练参数；工具config固定 `{connectionName,profileId,profileSha256}`，targetRef由原actor/material/connection pin派生，首切片训练spec来自该目标上明确注册的不可变规格，不接受模型shell/host/key。launch调用原custody时inputs固定 `{targetRef,callId}`，callId仅来自Agno注入的原FunctionCall；step/slot固定为本child的SSH训练操作，context绑定原child/run，不同callId或输入重复调用必须冲突。operation handle.id为原operation UUID，不是SSH PID或远端URL。对lookup/inspect/cancel由原operation绑定找回唯一lease；无新allocate。

helper通过已配置Python执行 `-I -B -m agent_factory.ssh_process_helper`，启动前核协议；只读依赖检查不自动安装。一次SSH调用输入一份有限JSON，stdout输出一份JSON，stderr不作为原操作证据。命令只有固定module与已验证解释器路径，输入不拼shell。可用actions为 `capabilities/submit/inspect/cancel/reclaim/output`。capabilities不写运行数据；其他请求含 `protocol/action/binding/spec/limits/root`，其中非submit携带同原规格只为核对，不授执行权。`binding`含 `leaseId/operationId/ownerId/taskId/runId/planId/planHash/requestId/targetFingerprint`；原endpoint/root与provider配置指纹仍由Factory保存并复核。spec/limits采用现ProcessSpec或ResearchProcessSpec和对应Limits的精确字段，不新增脚本语言或任意属性字典。

远端每lease使用独立0700目录、唯一原custody.sqlite与不可变binding描述。目录/描述首次持久化后，重复submit只能inspect原journal；创建过目录但journal缺失/不完整视为UNKNOWN，不重建/重启。launch权仅首次create返回的BoundedProcessAdapter对象持有。操作串行锁沿原目录flock保护，原journal仍是唯一进程状态源；绑定描述不另建状态机。取消和读取不能创建目录或journal。

response固定 `{protocol, binding, observation}` 或固定安全错误code；observation沿原snapshot的 `id/ownerId/taskId/requestId/specSha256/identitySha256/state/stoppedProof/stopReceipt/exitCode/enforcement` 及必要原process身份字段，响应限额与字段核对在接收端完成。`output`只在原停止与目录身份已确认后返回有限base64字节、字节数和sha256，不附私钥/环境变量；后续selected文件同原安全路径读取规则。Factory将原snapshot投影为现ResourceProvider receipt（processBinding/providerJobId/state/released/stopEvidence/enforcement）；未确认缺字段不得投影completed。custody RuntimeObservation沿既有schema，output仅含 `kind='ssh-process'`、原task/run/lease/job引用和已归档artifact引用；原stdout由artifact保持，不能把任意多行日志塞入受限observation格式。

首实现CPU受界进程只用于机制证明；ResearchProcessSpec环境/目录、GPU绑定与真实分配/释放仍按完整任务逐步接入。没有GPU证据不输出GPU RELEASED。协议字段/文件身份、恶意response、重复submit和未知目录均有portable反例；真实helper、sshd与PG等root串行授权后执行。

现ResourceService._reserve已先调用`execution_runtime(effectKey).validate_execution`再在原task行锁内核原run及(task,effect)唯一性。为SSH这一明确第二消费者，最窄扩展为所有验证过的explicit execution持久化`executionEffect`，只有实际提供requirement时持久化`executionGuard`；未注册effect仍拒绝，旧lease缺字段沿既有默认规则读取。SSH效果固定`ssh-process-run-v1`，其execution为`{nativeRunId,effectKey,requirement:{operationId}}`，runtime validate/guard核对该operation的owner/task/run/plan、adapter精确pin、工具配置targetRef与lease连接，不以requestId文本作为身份授权。provider从原executionGuard读取operationId，不解析请求字符串发明绑定。新增测试核SSH与旧bounded receipt保留各自语义、未知effect零allocate；资源层此接缝由主集成负责。

资源声明和平台准入上限不等于远端 kernel enforcement。preflight 必须返回实际可证明的隔离能力，不能把本机限制或环境变量当远端强制边界。GPU 运行需现 GpuBinding 绑定实际分配设备/namespace，并由可信目标适配器提供与原 lease/process 关联的占用及释放观察，经 validate_gpu_evidence 核对；CUDA_VISIBLE_DEVICES 仅进程选择，不是分配/独占/释放证明。现 GpuBinding 自身也明确 quotaEnforced/deviceIsolationEnforced=false；不得据此声称隔离外部进程。无实际 GPU 证明时可完成 CPU机制验证，但 GPU释放/D01仍 BLOCKED。

实际 stdout/stderr、退出码、选定指标和明确文件清单从原运行目录取回，经现 artifact_write 与研究精选证据契约归档；完整原结果保持 owner 私有，团队仅按现 sourceContentIds/精选字段与附件授权读取。拒绝越根路径、symlink 替换、跨运行文件和尺寸越界；先确认完整归档，再允许独立的显式清理，不把 reclaim 等同删除用户代码/数据。科学负结果保留；进程成功不自动代表目标达成。

明确新增窄公开应用读口（拟 `ApplicationRuns.ssh_results(owner, child_task_id, run_id)`）：当前成员/owner检查，原task/run/plan绑定，原operation精确SSH adapter pin及其lease/remote job身份，原launch/wait材料bindings和停止证据全部核对后，返回带 `kind='ssh-process'` 的原receipt、选定材料引用、exit/status、已归档artifact引用及provenance。它只读，不启动/续跑/刷新授权。研究证据消费者按明确SSH类型分支调用，不把它送入 MemberToolOperation CLI解析；原tool_results唯一CLI检查、personal-tool DONE格式与本地路径完全保留。缺失原绑定/停止或尚未取回的文件明确未完成，不用模型输出冒充真实receipt。精选字段/文件仍由原研究evidence配置确认，不自动将整个SSH输出分享。

### 4b. Operation adapter and archived result contract

`SSHOperationRuntime(store, resources, personal_ssh, profiles, *, pin=OPERATION_PIN)` implements the existing custody `start(context, operation_id, inputs)`, `lookup(context, operation_id)`, `inspect(context, handle)` and `cancel(context, handle)` methods, plus ResourceService `validate_execution(owner, task, plan, target_ref, execution)` and `guard_lease(lease)`. Installation registers that same instance in the existing custody runtime map and `resources.execution_runtimes[EFFECT]`; there is no new worker or recovery loop. `ssh_tool_registrations(runtime)` returns only the exact launch/wait registrations. The launch factory uses the governed BindingContext and explicit immutable profile and connection pin, never model-supplied SSH addresses, shell commands or credentials.

One native experiment child has one SSH training operation, matching the existing `(task,effect)` uniqueness. The effect slot is fixed `ssh-process`; original native tool-call identity and exact intent/inputs are checked, and a different repeated intent conflicts rather than silently replacing/reusing an execution. This initial trusted fixed process specification proves the mechanism only; varying training parameters across research rounds requires an explicit later input contract. It is not evidence of the complete remote research journey.

The existing custody operation ID, resource lease ID and remote journal `providerJobId` are distinct. Persisted lease `executionGuard.operationId` binds them with original owner/task/run/plan and the exact operation pin. The operation handle retains the custody ID. Only completed success has custody `output`:

```
{kind: "ssh-process", taskId, runId, leaseId, providerJobId,
 executionStatus, exitCode, artifacts: [{taskId, artifactId, sha256}]}
```

FAILED/CANCELLED keep `output=null` as required by the existing runtime contract. For every positively stopped process, including failure/cancellation, archive bounded stdout/stderr bytes and a compact receipt through the existing task artifact store before returning terminal custody. Files are private owner artifacts, not automatic team publications. Receipt filename is `ssh-<operationId>-receipt.json`, log filename `ssh-<operationId>-output.log`. Exact artifact provenance fields are `kind="ssh-process"`, `operationId`, `leaseId`, `providerJobId`, `nativeRunId`, `planId`, `executionStatus`, `evidenceRole` (`receipt` or `output`), `verificationStatus="unverified"`; existing artifact-write provenance additions remain intact. Receipt JSON contains `schema=1`, `kind`, `operationId`, `taskId`, `runId`, `planId`, `leaseId`, `providerJobId`, `processBinding`, `executionStatus`, `exitCode`, `allStopped=true`, `stopEvidence`, and `outputState='artifact'` with the exact output artifact reference. Only an original `stopEvidence.kind='never-dispatched'` permits `outputState='never_dispatched', output=null`: a never-launched journal has no stdout file. Missing output after any dispatched process is still an archival error, not empty output. Archive idempotence checks original task artifacts under the existing task metadata lock; it does not introduce another execution state table. Network retrieval precedes that short transaction. Archive failure does not invent a terminal result or remove the remote original evidence.

`ApplicationRuns.ssh_results(owner, child_task_id, run_id)` reads these already archived artifacts plus original custody/lease and plan only; it never calls a provider or SSH transport. It checks the caller, original task/run/plan, exact operation pin, `executionGuard.operationId`, `processBinding`, positive stop and the exact archive provenance. It returns the original compact receipt, output artifact references and exact selected launch/wait material provenance. Both successful and stopped negative results are readable; absent archive is explicitly incomplete. It cannot substitute a model-written receipt or accept an artifact based solely on its filename. Runtime `output` is not the source of truth for failed/cancelled receipts. The personal-SSH-to-resource-target construction seam remains subject to the separate minimum integration review; it must reuse `PersonalSSHServers.server` and `lease`, not raw credentials or a second agent pool.

### 5. Validation and delivery

先 portable 合同与原身份负例，再单个隔离 PG + 本机真实 sshd/透明 TCP 转发测试。实际运行一个受控短 CLI，覆盖失联、原生 child 暂停、硬重启、取消和文件回收；不使用真实 key/provider/GPU。保留首失败，重 PG 串行。随后实际研究 workflow 观察真实工具结果进行模型决策的确定性替身测试；它只证明协议，不替代正式模型 C 层。D01 仍需目标机、真实训练与允许的故障实验，未具备标 BLOCKED。

## Risks / Trade-offs

- 现 Agent external handler 原用于确认路径 → 实测自动原结果递交是否只继续原 run，检查重复命令、foreign requirement、父取消；不复制恢复逻辑。
- 远端 helper 缺失或隔离不满足 → 明确不可执行并保留配置，不自动安装/降级/假装GPU隔离。
- 转发断开或主机替换 → 按 pinned hostkey 拒绝/UNKNOWN，不重派；不由本项目管理代理基础设施。
- 实际集群只允许 scheduler → 生产路径保持 BLOCKED，追加真实 scheduler 适配规范，不把直接后端当已适配。

## Migration Plan

核心启动仅在显式 `Settings.ssh_training_profiles` 非空时装配 SSH operation runtime、精确 launch/wait registrations、原 OperationCustody pin 与 ApplicationRuntimeRegistry owner。profile 是部署提供的受信训练规格，不从环境变量、模型输出或 HTTP 创建可执行配置；成员仍选择自己的明确执行授权 SSH 连接。未配置 profile 的 standalone core 不安装训练入口，也不创建默认材料。唯一现有 process tick 按 effect 路由到该 runtime；不启动第二 observer。Research 通过材料与公开结果口使用该能力，不参与 core 装配。

资源装配复用原不可变计划与连接 pin，不要求 operator 为每个成员手工复制 target。`PersistentResourceService.register_target(ref, target)` 与初始化共用 ref、原配置、namespace/pool 校验；相同定义幂等，冲突拒绝。注册与列表快照只持短锁，不在锁内访问 vault/SSH。SSH runtime 从原材料构造成员特定 provider；同主机容量 namespace 不按成员、连接别名、训练规格或凭据版本分裂。主机密钥相同的入口共用一个容量责任；这不是对未测集群调度或设备隔离的承诺。

重启后的资源 API/维护可以先于任何新 launch：资源服务仅在 target 不在内存时调用已装配的 `ssh_targets.restore_target(owner, ref)`，该唯一具体消费者从该成员现有 lease 的原 plan、操作和连接 pin 重建并注册原 target。没有原 lease 不能由任意 ref 创建提交授权；原 pin 不再可授权时拒绝并保留 hold。恢复回调只读原身份和注册内存 provider，不执行 SSH 或新 allocate；原有 observer 再观察同一操作。

以显式新 adapter/material version 发布，不改旧 immutable plan。依赖并行去 demo 变更的正式认证和测试夹具；无数据库清空/凭据迁移。回滚停用新提交但保留原 adapter 的 inspect/cancel 能力与未决 custody；不能卸载原代码后声称已清理远端任务。

## Required target facts

正式运行前最少需要：Factory 可达的映射入口 host/port；最终 SSH 用户/主机公钥及已存在连接引用；允许工作目录；是允许直接运行还是必须经某个已安装调度器（名称及正常提交/查询/取消方式）；可用 Python/runtime 与训练入口/环境/数据位置；GPU资源分配方式与本次运行时限/预算、是否允许断线/取消验证。只要配置引用与非秘密元数据，不在聊天索要私钥。受控本机测试可先行，不能据此补写未知目标事实。

### SSH host capacity aliases

Provider capacity namespace derives only from the validated final SSH host public key and protocol, not actor/owner, registration reference, endpoint port, root, credentials or process specification. Aliases for that host must use the same fixed ComputePool definition; differing per-user declarations cannot multiply host capacity. Configuration fingerprint still includes the exact server/spec to prevent redirecting an original operation. This is an admission identity convention, not proof of physical topology: shared host keys across machines and cluster-wide scheduler pools require an explicit target pool decision and measured capacity before production acceptance. Target reconstruction uses the original immutable plan and connection pin; registration and restart restoration stay in the existing resource service, not a new endpoint registry.

The SSH operation runtime narrowly reuses `ProcessRuntimeService` original custody/stop/reclaim methods, overriding its exact effect/tool validation. Only the existing process-maintenance tick invokes its `observe_lease`; no second tick is scheduled and the new native tool never calls the inherited bounded synchronous `run`. Terminal output archival occurs in the original observation path before reclaim; reclaim does not delete remote data. Missing targets are restored from original plan/lease identity through the resource-service seam before the existing custody checks; already-installed original targets are not replaced.

### Personal connection and immutable training profile construction

Launch binding config is exactly `{connectionName,profileId,profileSha256}`. The trusted injected profile holds typed spec/limits, absolute interpreter and finite pool ceilings; its digest covers all these fields. Executable paths remain outside inert member material JSON. Original profile IDs are immutable and retained for original-plan recovery; a missing/mismatched profile rejects, never chooses a newer one. Launch registration requires environment connection adapter `owner-ssh-server-v1` and explicit `ssh:execute`; existing prepare-only grants do not upgrade. After validating the original full ConnectionRegistry pin, resolve its registrationRef and call `personal_ssh.server(actor, reference, required_capability='ssh:execute')` and the corresponding original `lease(...required_capability='ssh:execute')`. No raw credentials or separate SSH agent pool is introduced. Derived resource reference includes actor, exact material/pin and profile digest. Missing target restoration accepts only an existing owned original lease/plan, reconstructs that same reference, and registers through the resource service; ordinary arbitrary references cannot grant access. Host capacity pool identity is derived from the same host-key namespace with finite profile ceilings; conflicting ceilings for aliases are rejected.

For the CPU SSH provider there is no remote capacity allocator or deletion effect beyond stopping the original process. The existing maintenance path claims a durable release intent then confirms it through inspect. Consequently inspect may return RECLAIMED only when both the original Factory lease has `releaseAck` unknown/accepted and the original process has positive identity-bound stop proof; an uncertain release acknowledgement alone never proves stop. Runtime archival precedes the release claim. This rule does not apply to GPU/device allocation, which this provider rejects, and does not change the generic maintenance protocol.

### Unified CPU release archival precondition

`SSHProcessProvider` receives `archive_original(owner, lease_id)` from the original operation runtime. Every path about to return RECLAIMED, including direct reclaim and inspect after a prior release intent, awaits this callback first. Missing callback or archival error cannot release capacity; the original durable release intent remains held and later inspect may complete the same archival without another submit/cancel. This also governs the existing public ResourceService reclaim endpoint, not just maintenance. Archival's bounded raw-output read uses the output action, which never invokes this release callback, so no callback recursion or second ledger is introduced.

### Read-port and wait-name integration decision

The SSH wait name is `factory_wait_ssh_process`; Research root keeps its existing
`factory_wait_operations`. Existing child tool/material/capability subset checks
remain unchanged. The application result port takes only owner, original child
task ID and run ID. Core reads that exact owned task/run's persisted custody rows
and requires exactly one matching complete SSH operation pin before the existing
lease/stop/archive checks. Zero or multiple matches are unavailable; the app does
not supply operation identity or query core SQL. No generic operation-list API is
added, and unrelated custody operations are not returned.

### Original child lookup and bounded private observation

`ApplicationRuns.delegated_child(owner, parentOperationId)` reads the current member's original custody, requires the complete delegated-operation pin and exact parent identity, then the unique `operation:<id>` delegation link. It returns only child `taskId`, `runId`, `planId`; absent/unbound child returns null. Ambiguous or inconsistent binding rejects with `APPLICATION_DELEGATED_CHILD_MISMATCH` (409), while current-member/ownership errors remain 403/404. Failed/cancelled observations remain readable. No observer, admission or recovery runs.

`ssh_results(owner, childTaskId, runId)` additionally returns private `output: {text, truncated, utf8Valid, artifact}` after original artifact integrity/provenance checks, decoding only the first 16384 bytes with UTF-8 replacement. Never-dispatched output is null. This is untrusted execution data, not instructions or permission to publish. `SSHOperationWaits(..., commands=..., runs=ApplicationRuns)` supplies this checked status/exit/output to the original SSH requirement; it requires the same unique SSH operation, does not poll here, and reuses original command version/receipt recovery. At most one operation output enters a result, bounding payload independently of model behavior.

### Typed experiment input bound to the original operation

A trusted `SSHTrainingProfile` may declare the optional pair `input_schema` and `input_argument`. Both must be present or both absent. The schema uses the existing bounded object-schema validator; the fixed argument name is a nonempty bounded trusted string without NUL. Both fields participate in the profile fingerprint when present. No-schema profiles accept only an empty input object and preserve their fixed command behavior.

The launch model may provide only `inputs`, validated with `validate_input_values`. The derived ProcessSpec appends exactly two argv entries: the trusted argument name and canonical JSON for the validated object. There is no shell interpolation, executable/host/resource override or extra parser model. Constructing the complete derived ProcessSpec must enforce its existing maximum 32 arguments and 8192-byte serialized argv limit before target registration or SSH. Quoted strings and shell metacharacters remain data in the single JSON argv value.

The original custody intent persists `{targetRef,callId,inputs}` and its existing hash atomically. Recovery reads this original object, validates its hash and schema, and reconstructs only that original derived spec. Changed call/input replay conflicts with the same fixed operation slot. There is no new input table or recovery controller. The pure shared function `ssh_target_reference(owner, material_ref, connection_pin, profile_fingerprint, inputs)` binds the derived resource reference to the actual validated input object; ensure/restore/guard and the read-only application result port all use it. Input changes distinguish target configuration but never split the host-key capacity pool. Missing original inputs cannot be guessed from current model output.

The private output also reports `utf8Valid` by strict UTF-8 validation of the complete archived bytes (at most the existing 256KiB archive limit). Replacement characters are display only, not proof that the original bytes form valid JSON; research evidence selection rejects truncated or invalid-UTF8 output. No alternate decoding or repaired JSON is scientific evidence.
