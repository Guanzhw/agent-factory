# Spec Delta

## Purpose

让成员将受支持的应用根任务交给明确支持其契约版本的远程执行端，并在传输、授权、执行、取消和恢复过程中保留不可变输入、预算与原操作身份，防止版本降级、配置丢失和未知效果重放。

## ADDED Requirements

### Requirement: Strict versioned immutable application envelope

系统 SHALL 接受显式 v2 envelope 的准确字段 wireVersion、plan、applicationDefinition、sha256；wireVersion 与 plan.contractVersion MUST 为整数 2。sha256 SHALL 保持原计划摘要语义，完整定义 SHALL 使用既有应用版本摘要算法与 plan.applicationRef.sha256 核对，并验证定义、mode、schema、输入、配置及执行绑定与原计划一致。

#### Scenario: Exact v2 transfer
- **WHEN** 已启用 v2 的目标接收有效根任务及完整不可变定义
- **THEN** 执行端保留原 schema、inputValues、applicationConfig、applicationRef、材料与执行绑定，且效果收到原值

#### Scenario: Tampered or ambiguous envelope
- **WHEN** 定义摘要不匹配、mode/config/input 与定义不符、计划摘要不匹配，或含额外 envelope 字段、字符串版本、布尔版本或未知版本
- **THEN** 系统在新执行效果之前拒绝，不通过删字段或默认值修复请求

### Requirement: Frozen v1 compatibility

系统 MUST 保留 v1 wire reader、应用定义、计划摘要、回执及恢复语义；v2 SHALL 不自动降级为 v1，且 v1 SHALL 不被重写为 v2。

#### Scenario: Existing v1 operation resumes
- **WHEN** 升级后读取原 v1 handoff、授权回执及运行记录
- **THEN** 使用原摘要与身份恢复，不迁移定义字节或创建替代操作

### Requirement: Explicit target and receiver capability

远程目标 SHALL 声明 supportedApplicationContracts，未配置时仅支持 v1，v2 必须显式启用。目标列表 SHALL 区分静态声明与连通性验证；receiver SHALL 在 prepare 自行验证实际支持范围，不信任客户端声明或推测支持。禁用新 v2 接收 SHALL 不授权替换原操作。

#### Scenario: Unsupported receiver
- **WHEN** 目标未声明 v2 或实际 receiver 不支持请求契约
- **THEN** 请求以明确不支持错误拒绝，无新效果且无自动降级

#### Scenario: Capability display
- **WHEN** 成员查看远程执行目标
- **THEN** 页面展示已声明的应用版本能力，未验证连接不显示为已验证

### Requirement: Version-correct authority budgets

v2 的准备、授权回调、执行与恢复 SHALL 使用 operationSeconds，v1 SHALL 使用 experimentSeconds。系统 MUST 拒绝混合版本预算和缺失版本必需字段；当前权限校验和原授权身份验证 SHALL 继续执行，不扩大预算或缓存授权。

#### Scenario: V2 authority recovery
- **WHEN** v2 操作在准备或派发回执丢失后恢复并重新核对权限
- **THEN** 原版本、operationSeconds、source plan 摘要及绑定保持一致，撤权或取消仍阻止新效果

#### Scenario: Mixed time budget
- **WHEN** v2 请求或其授权包含 experimentSeconds，或省略 operationSeconds
- **THEN** 在新效果前拒绝，不从另一版本时间字段补值

### Requirement: Root-only supported runtime boundary

首版 v2 handoff SHALL 仅支持已验证的根任务 native agent 执行路径；workflow、scientific envelope、delegation、已有远程 handoff 和嵌套 placement MUST 明确拒绝。支持某个应用版本 SHALL 不代表支持全部 runtime 或组件类型。

#### Scenario: Nested or unsupported component
- **WHEN** v2 请求携带 workflow、scientific 或委派语义，或试图转交已有远程任务
- **THEN** 系统在准备新执行之前拒绝，不能静默丢弃原字段后接收

### Requirement: Original-operation recovery and stop evidence

系统 SHALL 在重复请求、丢失回执、重启和取消时继续核对原操作、owner、原 receiver、plan 摘要与绑定。UNKNOWN 或未确认停止的效果 MUST 保持原容量约束且不得重派；状态 GET SHALL 仅观察，后台或显式控制负责核对与收尾。

#### Scenario: Concurrent duplicate dispatch and restart
- **WHEN** 同一 v2 操作并发重复派发或 receiver 在回执送达前重启
- **THEN** 恢复原回执与原 native 身份，实际效果至多启动一次，并读取原产物字节

#### Scenario: Cancellation with uncertain effect
- **WHEN** 已请求取消但尚无原效果的停止证据
- **THEN** 保持 UNKNOWN 或取消中及容量占用，状态读取不触发 provider 控制或释放，后台确认停止后才收尾
