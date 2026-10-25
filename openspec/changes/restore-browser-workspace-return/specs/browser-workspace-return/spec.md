## ADDED Requirements
### Requirement: 原登录目标恢复
系统 SHALL 在原OIDC flow成功完成后恢复登录前根工作区目标，并复用平台授权与导航。
#### Scenario: 项目深链接登录
- **WHEN** 用户从带项目query的工作区开始登录并完成原state
- **THEN** 返回同一query/hash，原导航和资源授权决定可见页面。
#### Scenario: flow后服务重建
- **WHEN** 登录开始后服务重建
- **THEN** 原flow仍恢复已保存目标，不使用新请求替换身份。
### Requirement: 返回目标不能改变来源或认证边界
系统 SHALL 仅接受有界根工作区目标。
#### Scenario: 外部或非工作区目标
- **WHEN** 提交外部、协议相对、反斜线、控制字符或非根路径目标
- **THEN** 创建flow前拒绝，不发起身份交换。
#### Scenario: callback目标注入
- **WHEN** callback携带额外返回目标字段
- **THEN** 原严格callback参数检查拒绝，错误返回静态首页。
