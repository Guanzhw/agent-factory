## ADDED Requirements
### Requirement: 无预算终态夹具准确表示服务缺席
终态竞态测试 SHALL 显式将无绑定预算服务设为None，避免Mock伪造完成上下文。

#### Scenario: 正常或失败终态沿原无预算路径结束
- **WHEN** 夹具无app finalizer且无budget scope
- **THEN** 原停止、失败、取消与释放顺序断言保持成立，不进入预算完成路径
