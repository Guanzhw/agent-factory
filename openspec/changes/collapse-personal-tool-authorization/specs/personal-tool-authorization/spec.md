## ADDED Requirements

### Requirement: 单次授权保留原身份且只执行一次通用guard链

个人工具 SHALL 在每次授权callback独立调用一次既有Store工具授权链，保留原task/plan/native/function/adapter身份、当前预算、取消、成员与共享权限和retained handle校验。

#### Scenario: 正常授权
- **WHEN** 原任务调用已绑定个人工具且权限有效
- **THEN** 完整execution guard链与绑定guard各执行一次，所选工具通过，原效果身份不变

#### Scenario: 缺失或替换可信绑定guard
- **WHEN** execution-bindings guard被删除、替换或指向其他bindings对象
- **THEN** callback拒绝，不解析凭据或派发工具，实例方法替换不能伪装成可信guard

#### Scenario: 原计划不一致
- **WHEN** Store返回plan与捕获的binding plan不一致
- **THEN** 拒绝工具调用，不创建新效果

### Requirement: 独立边界继续读取新鲜权限

系统 SHALL 保留每次新callback、凭据解析前后、原receipt重放与结果交付的权限校验，不缓存跨边界authority，不重派UNKNOWN。

#### Scenario: 下一callback前撤权
- **WHEN** 首次授权后发生撤权、预算停止或任务停止
- **THEN** 下一callback拒绝，不能复用先前通过结果

#### Scenario: 凭据读取期间撤权
- **WHEN** vault读取过程中原权限撤回
- **THEN** 读取后授权拒绝，不返回凭据或成功结果

#### Scenario: 原收据重放
- **WHEN** 原调用已有完成收据或UNKNOWN
- **THEN** 完成收据经当前权限检查后读取，UNKNOWN仍不派发新效果
