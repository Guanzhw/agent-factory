## ADDED Requirements

### Requirement: 独立完成回执

完整PG验收 SHALL 在runner正常返回后写入可选JSON完成回执，并由独立CI步骤验证；缺失、无效或accepted非true不能通过。

#### Scenario: 正常完成
- **WHEN** 全部选定测试正常执行且required cases通过
- **THEN** 回执含运行/选择/跳过/失败/错误计数及groups，CI短输出accepted结果

#### Scenario: 提前退出但退出码为零
- **WHEN** 子进程退出0却未产生完成回执
- **THEN** 独立校验失败，不能以退出码代替完整验收

#### Scenario: runner提前停止
- **WHEN** result.shouldStop为true
- **THEN** accepted为false，即使已执行required tests通过

#### Scenario: 失败或required跳过
- **WHEN** 测试失败或required case被跳过
- **THEN** 回执accepted为false，CI校验失败

#### Scenario: 可选class跳过
- **WHEN** optional class通过setUpClass显式跳过
- **THEN** 保留跳过事实，不机械因selected大于testsRun否定既有合法跳过
