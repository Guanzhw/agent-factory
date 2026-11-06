# Spec Delta

## Purpose

可信团队成员自行接入、发现与使用属于自己的资源。资源接入保持账号身份、可见性和凭据归属的一致契约，同时消除退役审批路径、隐式列表截断与重复客户端规范化造成的阻碍。

## ADDED Requirements

### Requirement: Account identity is consistent
系统 SHALL 允许合法账号标识用于资源操作及OIDC映射，包括邮箱形式和sk-开头标识；仍拒绝非法或错所有者元数据。

#### Scenario: Email account configures a tool
- **WHEN** alice@example.com创建并绑定自己的工具资源
- **THEN** 不因资源引用格式而拒绝其账号标识

### Requirement: Flat discovery returns all visible choices
现有未声明分页的应用、个人资源及凭据列表 SHALL 不因前100条历史或其他类型记录而隐藏可用选项。

#### Scenario: History exceeds one hundred rows
- **WHEN** 多于100条历史草稿或其他资源排在一个可用应用/模型/SSH资源之前
- **THEN** 该可用选项仍出现在对应目录并可按标识选择

### Requirement: Accepted model endpoint remains usable
客户端 SHALL 保留服务端接受的模型端点值，不以第二次URL字节规范化的一致性作为列表和恢复条件；仍验证URL语法、协议与嵌入凭据边界。

#### Scenario: Unicode endpoint path
- **WHEN** 服务端已接受并返回包含Unicode路径的模型端点
- **THEN** 模型列表、默认选择和原请求恢复可正常使用该配置

### Requirement: Retired approvals add no executable gates
系统 SHALL 保留历史审批读取与退役写接口的410语义，不再保留无消费者的审批写客户端或恒允许权限分支；当前所有权、共享撤销、凭据与成员边界继续生效。

#### Scenario: Member self service
- **WHEN** 有效成员接入资源或发布自己的定义
- **THEN** 不要求管理员额外批准；不属于该成员的私有资源仍不能读取或绑定
