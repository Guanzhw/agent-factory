# Spec Delta

## Purpose

让研究成员在正常部署配置下，以一次目标连续完成真实代码任务，无需因固定八次工具上限反复手动续轮；同时保留既有显式预算、已完成结果和停止边界，准确呈现达到额度后的状态。

## ADDED Requirements

### Requirement: Configure tool capacity through normal startup

系统 SHALL 通过正常启动配置接受 1–128 的工具次数上限，未配置时保持 8；新研究会话采用当前部署工具默认，成员仍可选择较低值，已有会话与任务的显式额度不得被回写。

#### Scenario: Apply the configured default
- **WHEN** 部署配置工具上限 32，成员新建研究会话且使用默认值
- **THEN** 新会话及其任务使用 32；合法第 9 次工具能够执行，成员无需逐次修改高级参数

#### Scenario: Reject invalid startup values
- **WHEN** 配置为 0、129 或非整数
- **THEN** 启动配置明确失败；缺省配置仍为 8，不静默退回更宽上限

### Requirement: Complete a coding goal without artificial stage breaks

系统 SHALL 在选定有限额度内支持一次目标贯通复现、定位修改、目标及完整测试、补丁核对和结束；不以自动创建新轮次规避额度。结果必须来自真实回执，未完成时如实说明。

#### Scenario: Finish the prepared public repository task
- **WHEN** 成员在已核来源和依赖环境的公开仓库副本中，一次要求修复已知缺陷、运行目标及完整测试、核对 diff 后停止，部署工具候选 32、操作 60 秒、运行 300 秒
- **THEN** 助手完成原轮目标，需要超过 8 次工具时仍可继续；保留红测与改后通过回执、最终 diff 和未改测试的依据；无观察后人为先停或额外人工修复续轮，独立验收者在结束后只读核对结果
- **AND** 记录实际工具数、模型请求、墙钟和人工干预；实模未用到第 9 次时只标该分支未覆盖，不强迫拆分工具或以次数否定任务成功；第 9 次能力另由原生 PG 验收。若 32 或现有时限不足，保留失败，不宣称候选充分

### Requirement: Preserve explicit budgets and actual outcomes

系统 SHALL 保留旧任务及成员自选的较低预算，超过额度不得产生新工具副作用；预算拒绝的真实状态、已完成结果与可继续条件必须可核对。部署上限改变不承诺原生收尾形式不变，也不得把拒绝误说成成功或未知副作用。

#### Scenario: Reach a lower budget under the higher deployment cap
- **WHEN** 部署上限 32，旧任务或新会话自选额度 8，助手提出第 9 次工具
- **THEN** 第 9 次执行前被拒，已有 8 次结果保留；实际拒绝与停止状态可查，不将已确认完成的操作变为 UNKNOWN，也不显示任务已完成
- **AND** 返回原会话不自动执行；核原状态安全后成员可显式继续，记录真实启动动作及新轮身份，不重放旧操作

#### Scenario: Keep ownership and interruption boundaries
- **WHEN** 两用户分别以不同额度并发执行，或原任务已有 UNKNOWN、收到停止或权限撤销
- **THEN** 计数和结果仍归原用户及任务；既有拒绝、取消与未知结果核对继续生效，不因提高部署上限而获得额外权限或自动重放
