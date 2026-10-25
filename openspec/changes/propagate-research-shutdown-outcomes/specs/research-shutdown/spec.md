## ADDED Requirements

### Requirement: 关闭期限与原操作持有
部署服务 SHALL 为原科研执行及其cleanup保留依赖，完整关闭链共用现有35秒期限；超过期限自行以非零状态退出，允许未完成本地清理被中断。core库仅提供可选进程策略注入。

#### Scenario: 原清理未在期限内结束
- **WHEN** 原cleanup仍需数据库或服务图且35秒期限到达
- **THEN** 服务进程实际非零退出，不以抛异常冒充退出
- **AND** 未确认停止的effect与容量仍保留，退出不构成外部停止证明

#### Scenario: 原UNKNOWN跨重启保留
- **WHEN** 同数据库和持久状态重新启动服务
- **THEN** 核对原task/run/control身份，不重派发原意图或创建替代控制器
- **AND** 未取得原操作停止证明前不释放容量

#### Scenario: 所有清理完成
- **WHEN** 原执行和所有晚生cleanup已结束
- **THEN** 应用、observer、native与共享依赖按顺序释放，关闭护栏取消
