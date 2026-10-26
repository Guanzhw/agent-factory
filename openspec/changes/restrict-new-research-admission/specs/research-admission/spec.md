# Spec Delta

## Purpose

让成员新建 Research 执行时进入具备实际轮次和终态链的当前固定研究组件，同时根据持久请求保留历史原操作的读取、恢复和取消边界，避免升级或误选模式生成另一条执行路径。

## ADDED Requirements

### Requirement: 新研究只使用当前固定组件
系统 SHALL 在没有持久原启动命令的新请求中，要求所选应用 mode 的完整 native component pin 与当前安装的研究 Workflow 相同；不兼容或未安装时返回明确原因，零新 scope/allocation/experiment/round/task/dispatch，不隐式转入历史首轮执行。

#### Scenario: 新项目误选 experiment 或其他应用
- **WHEN** 已确认项目选择无研究 pin、错误 pin 或 experiment mode，然后通过公开 Research start 请求新执行
- **THEN** 明确拒绝该新准入；兼容的当前研究 mode 仍可正常建立唯一研究轮次

#### Scenario: 未安装研究 Workflow
- **WHEN** 仅安装 Research 项目/历史端口，没有当前研究 Workflow
- **THEN** 新执行不可用且公开 start 拒绝；历史读取与原请求恢复端口仍保留

### Requirement: 持久原请求优先于当前新准入判别
系统 SHALL 用持久 owner/request 命令和原项目、expectedVersion 指纹识别原启动/续接意图，先核对并恢复原 intent；不根据当前目标或当前可用 pin 将原请求改派。其他 owner、不同项目/版本或复用其他动作请求键 MUST 冲突或拒绝。

#### Scenario: 历史首轮或旧 round 回执在升级后重读
- **WHEN** 原命令已提交，当前组件 pin 已变化或项目已修订/结束，原 task 为 reserved、UNKNOWN 或已完成
- **THEN** 使用原 request/task/run/allocation 返回原收据，无新分配或 native dispatch；历史和原取消入口不受新准入限制影响

#### Scenario: 原 intent 尚未绑定 task
- **WHEN** 原命令与 allocation 已持久但尚无 task，用户恢复同一原命令
- **THEN** 仅沿原保存的请求交给既有 core 准入复核；项目结束、scope 关闭或原执行组件不可用时明确阻止新效果，不替换 pin，不把缺失收据当未执行证明

#### Scenario: 旧 paused Workflow 缺少原实现
- **WHEN** 历史任务暂停但部署没有原 pin 对应执行实现
- **THEN** 保留原事实、收据与清理入口，真实续执行能力明确未成立；不得换成新 pin、重派替代任务或宣称兼容执行成功

### Requirement: 选择器反映当前研究能力
Research 执行选择器 SHALL 使用后端公布的当前完整 workflow pin，只提供匹配的已发布应用/mode；无兼容项或现有配置不兼容时解释原因，不自动替换已有约定。通用应用仍从既有 core 工作区使用。

#### Scenario: 同一发布应用包含 research 和 experiment
- **WHEN** 成员打开执行配置，目录同时包含固定 research mode、experiment mode、名称相同但 pin 不同的 mode
- **THEN** 只有完整 pin 匹配者可作为新研究选项；旧配置可见为不兼容，保存按钮不将它默认为其他模式
