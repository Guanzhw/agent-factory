# Research self-service setup

## ADDED Requirements

### Requirement: Explicit owner setup
研究应用 SHALL 提供无JSON粘贴的资源选择与定义保存/发布入口，复用core成员、凭据与治理；默认安装不得创建任何材料或发布应用。

#### Scenario: Empty catalog
- WHEN 成员打开空库setup
- THEN 只返回当前可用资源与缺项；无材料、应用、任务写入，缺项引导既有资源入口

#### Scenario: Save then publish
- WHEN 成员选择准确模型/环境/实验工具并保存，再明确发布
- THEN 保存只建owner setup草稿，不产生材料/应用版本；发布核对当前资源与pin，得到真实published applicationRef，不执行模型/工具/训练

### Requirement: Shared definition, personal resources
共享定义 SHALL 只包含材料与symbolic连接要求；执行连接选择只归当前成员。

#### Scenario: Two members
- WHEN Alice发布研究定义，Bob选择同一定义与自己的符合要求连接
- THEN application与material hash不变，Bob不继承Alice连接/凭据，撤销后当前权限核对阻止后续使用

### Requirement: Original request recovery
setup SHALL 保留原事务收据，不因响应丢失另建版本。

#### Scenario: Lost response and restart
- WHEN 保存/发布提交后响应丢失并重启
- THEN 同owner同requestId读取或重投得到原结果，材料和应用版本数不增加；同键异内容拒绝

#### Scenario: Partial governance failure
- WHEN 事务内任何材料或应用检查失败
- THEN setup与治理写入一起回滚，不能留下伪published配置；缺真实环境/工具不以fixture兜底

#### Scenario: Resource visibility is not a binding
- WHEN 共享模型可见但当前成员还没有connectionRef
- THEN 引导现有显式绑定入口；GET不绑定，registrationRef不能替代执行ref

#### Scenario: Preview workflow changed
- WHEN 保存preview后已安装workflow pin发生变化
- THEN 发布拒绝并要求重新查看确认，不静默发布新pin
