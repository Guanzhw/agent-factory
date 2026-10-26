## Purpose

使原生委派任务的正文与停止控制元数据分别遵守其真实责任，正常文本和结构化结果能在预算内完整传递，已停止的预算违例可明确结束，同时保留原任务身份、原等待和未知操作不重派的可靠性边界。

## ADDED Requirements

### Requirement: 原委派正文使用独立数据合同

系统 SHALL 完整保存原生委派任务在原输出预算内的 JSON 结果，允许正常换行、URL、Unicode、超过 4096 字符的文本和任意合法业务键。正文不能因控制字段黑名单被拒绝，正文以外的元数据继续遵守原身份和结构约束。

#### Scenario: 普通正文进入现有消费者
- **WHEN** 原 child 子树已正向成功停止，正文包含多行、URL、业务 token/host/command 键且 UTF-8 JSON 大小不超过原输出预算
- **THEN** 同一原 operation 闭合为 COMPLETED，持久化与读取的 result 与原正文相等，原 wait 后续步骤、本轮研究结果和前轮上下文得到同一完整结果

#### Scenario: 大于旧控制上限的合法正文
- **WHEN** 正文超过 16 KiB 但仍在原 child 输出预算内
- **THEN** 完整保留正文并闭合，不截断、不另建操作或结果账本

#### Scenario: 控制字段仍不可被正文规则放宽
- **WHEN** adapter/pin/owner/task/run 不匹配，或控制元数据含非法路由字段、非法形状或超出原限额
- **THEN** 拒绝该控制数据，不能通过将字段称作正文获得执行、跨 owner 读取或停止授权

### Requirement: 输出预算失败不伪装为执行未知

系统 SHALL 仅在原子树已经正向停止后，将不能表示为 JSON 或超出原 child 输出预算的结果标记为明确的技术失败，并闭合该原 operation；不得截断正文后宣称成功，也不得仅因该结果错误保留 UNKNOWN。原 native 结果和任务身份保持不变。

#### Scenario: 预算边界和超限
- **WHEN** 完整正文 UTF-8 JSON 字节数恰等于原输出预算
- **THEN** 完整成功；多一个字节则原 operation 返回明确结果容量失败，allStopped 为真，原 effect 可结算，不能被科学判定为成功

#### Scenario: 非 JSON 结果
- **WHEN** 已停止 child 的返回值不能无损表示为 JSON
- **THEN** 返回明确结果格式失败，不把无正文或截断值作为成功结果，不改变原 native 数据

#### Scenario: 仍有未知效果
- **WHEN** native child 已返回正文但其子树仍有未知或运行中的效果
- **THEN** operation 保持原非终态，不能用正文合法或超限代替正向停止证明

### Requirement: 保留原读取和恢复行为

系统 SHALL 沿同一原 operation、child、native run 和 requirement 读取及恢复，不改变现有已闭合记录的正文形状，不因部署修复创建替代执行；原控制合同对非委派适配器继续有效。

#### Scenario: 原暂停任务重启后取得完整结果
- **WHEN** 实际原生工作流已暂停，服务重启后原 child 成功停止并返回合法多行大正文
- **THEN** 原 operation 闭合，原 requirement 继续一次，后续模型步骤收到完整原正文，重复观察不新增 child/operation/dispatch

#### Scenario: 原短正文及其他适配器
- **WHEN** 读取已有短单行 COMPLETED observation，或处理非 native-delegated 适配器的 observation
- **THEN** 原已闭合结果保持可读且不改写；其他适配器不获得新的任意正文例外
