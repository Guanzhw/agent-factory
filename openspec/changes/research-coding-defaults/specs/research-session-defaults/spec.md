# Spec Delta

## ADDED Requirements

### Requirement: Ordinary startup supports the validated coding workload

系统 SHALL 在未显式设置三个已有执行参数时使用32次工具、120秒操作和300秒原生运行。新 Research 会话的默认选项、准备结果及原生执行 SHALL 使用同一配置，不依赖测试专用覆盖。

#### Scenario: A member starts a new coding session
- **WHEN** 部署未覆盖工具和时限参数，成员使用自己的有效模型建立新研究会话
- **THEN** 会话预算为32次工具和120秒操作，原生 Agent cap为32且运行及个人模型请求时限为300秒

#### Scenario: An operator explicitly configures lower bounds
- **WHEN** 部署显式配置8次工具、8秒操作、60秒原生运行
- **THEN** 新会话和运行使用显式值，不静默升额或回退到新默认

### Requirement: Existing durable task bounds remain authoritative

系统 SHALL 保留旧会话与 Plan 的持久预算、已知结果及未知操作记录，不通过修改启动默认回写旧额度或重放操作。当前 worker 原生配置的变化 SHALL 在使用说明中明确。

#### Scenario: A stored low-budget task reaches its ninth tool call
- **WHEN** 新默认运行环境处理原工具额度为8的 Plan，模型尝试第9次工具调用
- **THEN** 持久预算守卫拒绝该调用，零新增副作用，原结果保留
