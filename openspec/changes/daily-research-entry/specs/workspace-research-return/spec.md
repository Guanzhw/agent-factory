# Spec Delta

## ADDED Requirements

### Requirement: Daily entry points correspond to member tasks

系统 SHALL 以应用、我的任务、我的资源提供日常入口，保留作者与维护次级入口、旧有效地址和现有账号权限。应用入口 SHALL 进入真实独立应用，不将内部运行定义冒充普通模板。

#### Scenario: Enter and leave Auto Research
- **WHEN** 成员从应用打开已安装的Auto Research并返回平台
- **THEN** 使用真实独立首页与工作区，当前导航准确，返回不创建任务

### Requirement: Resource setup returns to its actual origin

系统 SHALL 保留原研究项目或个人会话位置和非秘密草稿，包括项目准备、执行参数及配置编辑的未保存输入；资源操作只有确认保存后才显示保存成功反馈。未知结果 SHALL 保留原请求核对；首次提交当前阶段被明确拒绝时显示拒绝、不自动离开，允许修正后由成员重新提交，不能宣称先前已确认阶段未发生。查询原请求失败不得推断原操作未执行。普通返回或明确放弃 SHALL 保持可用。秘密不得保存到URL或浏览器草稿。

#### Scenario: Complete a missing model for a new research session
- **WHEN** 成员填写目标和边界后进入模型配置，修正字段错误并确认保存
- **THEN** 可回原草稿继续，目标、边界和配置的输出额度不丢，不自动执行或改绑已有会话

#### Scenario: A save result is unknown
- **WHEN** 保存请求已发出但回执未确认
- **THEN** 不显示保存成功或自动离开，沿原请求查询，不发替代保存

#### Scenario: A save stage is explicitly rejected
- **WHEN** 当前模型配置或设默认阶段的首次POST收到明确403或422拒绝
- **THEN** 显示该阶段未接受、保留可修正输入，不自动离开；此前已确认的凭据或模型配置不被宣称未发生

#### Scenario: Looking up the original receipt fails
- **WHEN** 已发送请求的回执GET返回403或404，或仍无法确认结果
- **THEN** 保留原标识待核对，不以查询失败释放原请求或创建替代POST

#### Scenario: Return to an unfinished project edit
- **WHEN** 成员在项目准备、执行参数或配置编辑中填写输入，进入资源后返回，或在往返过程中后退前进与刷新
- **THEN** 恢复该成员、项目和配置版本/编辑目标对应的原输入及位置，不自动保存、发布、接受提案或执行；不同项目不混用草稿

#### Scenario: Leave or change the authenticated member
- **WHEN** 确认退出、认证失效或切换成员
- **THEN** 清理本片项目草稿，下一位成员不能看到它们；凭据值从未写入持久草稿

### Requirement: Navigation retains meaningful in-progress edits

系统 SHALL 在离开存在实际未保存输入的资源表单时保留可安全保留的内容或让成员明确放弃，不能因资源分类切换、给另一模型设默认而悄然清除。现有换成员与退出后的私有草稿清理 SHALL 保持。

#### Scenario: Select a different default while editing
- **WHEN** 成员编辑新模型时把另一条已有模型设为默认
- **THEN** 默认选择获得真实反馈，当前新模型输入和输出额度不被清空
