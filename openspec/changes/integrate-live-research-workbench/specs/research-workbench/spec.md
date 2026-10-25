## ADDED Requirements

### Requirement: Independent platform and live research navigation
系统 SHALL 保留独立平台首页、公共认证与已确认工作台布局，正式研究页仅显示真实应用数据。

#### Scenario: Platform round trip
- **WHEN** 成员从平台进入研究、查看项目并返回平台或刷新/前进后退
- **THEN** URL与当前页一致，模型/连接返回保留来源，默认core未安装应用时无研究死链接

#### Scenario: Empty or failed read
- **WHEN** 当前成员没有项目或读取失败
- **THEN** 分别显示空状态及创建/资源入口，或错误及明确重读操作，不显示固定示例项目/指标/助手回复

### Requirement: Goal versions and original command recovery
系统 SHALL 使用真实项目目标版本及既有原请求恢复，确认约定不自动表示启动。

#### Scenario: Ambiguous mutation and reload
- **WHEN** 创建/修订/确认/结束收到408、网络不确定或5xx后刷新
- **THEN** 保留该owner原request与payload，核对原请求，不以新键重复创建；其他owner不读取该意图

#### Scenario: Concurrent goal revision
- **WHEN** expectedVersion与服务端当前版本不同
- **THEN** 呈现冲突并要求读取最新目标，不能覆盖历史或自动确认新目标

### Requirement: Execution and evidence are distinct facts
系统 SHALL 分别展示准入/执行/科学结论和证据来源，不将缺少的数据推断为成功。

#### Scenario: Unknown original operation
- **WHEN** 原运行回执或操作结果未知
- **THEN** 展示原身份与UNKNOWN及核对入口，不以新请求重派或宣称清理完成

#### Scenario: Evidence-backed assistant
- **WHEN** 真实助手响应或团队记录可读取
- **THEN** 展示真实来源和事实/agent分析区别，未接入接口时不伪造消息、记录或指标

### Requirement: Complete journey verification
系统 SHALL 保留桌面/窄屏/键盘行为及真实API端到端验证，合成transport不替代真实模型/GPU。

#### Scenario: Two member browser acceptance
- **WHEN** 独立成员完成平台、项目、目标确认/修订、执行读取、资源与退出重登流程
- **THEN** 项目与原写入意图按owner隔离，团队内容只按实际授权读取，console错误和失败证据单独记录
