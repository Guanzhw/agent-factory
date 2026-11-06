# Spec Delta

## Purpose

浏览器和服务端围绕原请求识别完成、明确拒绝与未知结果，不把最新可变投影误认为原命令回执。成员可继续处理已明确拒绝的操作，同时保持丢失确认时不重复执行的保证。

## ADDED Requirements

### Requirement: Direct prewrite rejections settle browser pending
计划与工具接入 SHALL 在明确的直接写前拒绝后解除对应等待指针并保留已保存配置；未知冲突、失联或恢复查询失败不得被当成未执行证明。

#### Scenario: Withdrawn application rejects schedule
- **WHEN** 应用撤回导致计划创建在写入命令前被明确拒绝
- **THEN** 浏览器显示拒绝原因并允许修改，不永久等待不存在的命令

#### Scenario: Lost tool acknowledgement
- **WHEN** 工具绑定请求确认丢失且无法取得原回执
- **THEN** 保留原请求待恢复，不生成替代绑定

### Requirement: Recovery identifies the original command
计划命令恢复 SHALL 返回原命令的完成身份与当前计划投影；后续合法编辑不得使已完成原命令永久pending。

#### Scenario: Another editor changes the schedule
- **WHEN** A的修改完成但确认丢失，随后B再次修改同一计划
- **THEN** A按原命令恢复为完成，当前投影可以反映B的修改

### Requirement: Composition retains exact application version
应用选择及提案恢复 SHALL 保留所选的精确版本引用，不用同ID的首个版本替代，不把未变更输入标为已修改。

#### Scenario: Older published version selected
- **WHEN** 同一应用有两个已发布版本且用户选择或恢复旧版本
- **THEN** 装配引用旧版本且未改变的输入保持干净
