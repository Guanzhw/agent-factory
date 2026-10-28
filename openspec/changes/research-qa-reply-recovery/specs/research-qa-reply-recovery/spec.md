# Spec Delta

## Purpose

让已可靠保存的私问回复在执行服务意外退出后被原任务安全复用，避免再次请求模型。恢复仍受原始运行身份、双方当前来源权限和真实终态约束，并如实保留尚未保存结果及未核实部署的边界。

## ADDED Requirements

### Requirement: Recover the saved original reply

系统 SHALL 在原任务重领时复用已保存的原私问回复，零新增模型请求，不新增消息或执行身份，并通过原生运行正常结束原 run。没有已保存回复时 SHALL 保留原问答路径；关联分析结果不是私问回复。

#### Scenario: Reply committed before service exit
- **WHEN** B 的回复已提交，服务进程在原生执行落终态前退出，原 task/run 随后被队列重领
- **THEN** 模型调用增量为零，原 reply 正文/来源/时间及 message/task/run 不变，原生执行正常完成，并在现有终态条件满足后结算原分配

#### Scenario: Reply absent or association task
- **WHEN** 原私问回复未保存，或任务属于关联分析
- **THEN** 系统执行其原有路径，不套用已保存私问回复成功短路，不声称这些窗口获得零重算保证

### Requirement: Verify original identity and current authority

复用前系统 SHALL 核对原 owner/task/run/message/endpoint 配置、原输入和完整依赖，及双方当前成员和来源读权。身份不符、原输入缺失/不符或任何原依赖撤回 MUST 拒绝且零新增模型，不重新选来源绕过。

#### Scenario: Invalid identity or withdrawn input
- **WHEN** 恢复使用其他 owner/run，或原输入/配置不符，或任一参与者成员资格及任一原来源（含未引用来源）已撤回
- **THEN** 系统拒绝复用和新模型请求，保留原绑定/记录，回复读取继续遵守现有正文隐藏规则

### Requirement: Reply does not prove task completion

已保存回复 SHALL 只证明回复提交。系统 MUST 保留取消、未知 effect、受管进程 custody 和原预算事实；不得凭 reply 清除未知操作、伪造成功或提前释放额度。

#### Scenario: Saved reply with unresolved operation
- **WHEN** 原回复存在但任务仍有未知 effect 或未结束受管进程
- **THEN** 系统保留原状态与额度，直到现有真实终态条件满足才完成结算

### Requirement: Honest deployment and history boundary

系统 SHALL 保留历史记录受权读取，使用真实的新实现指纹，不改绑或自动重放旧任务。部署切换 MUST 先核实目标旧版本在途状态；未接入不等于无在途，存在真实在途时先保留原运行版本完成再切换，不承诺旧 pin 的透明执行兼容。

#### Scenario: Deployment target unverified or in flight
- **WHEN** 目标部署尚未核实，或仍有旧 pin queued/running/paused/结果未确认任务
- **THEN** 不直接在该部署切换代码，不删除旧记录、不伪造原 pin 或重放任务；无关的隔离实现与验证可继续
