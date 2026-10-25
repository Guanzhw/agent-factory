# Spec Delta

## Purpose

将研究原执行中明确选择的实际证据自动保存并发布为团队可读记录，提供带源码、配方、数据条件和负结果的可继续成果。权限、原操作身份与缺项必须可检查，不以模型陈述、可下载文件或执行成功冒充科学验证。

## ADDED Requirements

### Requirement: Confirmed selection controls disclosure
系统 SHALL 仅按owner确认目标版本中的精确CLI材料及有限字段选择公开原输出，模型、程序或未选产物不能扩大分享范围。

#### Scenario: Selected metrics and private canary
- **WHEN** 原CLI输出选中metrics/source/recipe与未选privateCanary
- **THEN** 自动记录只有选中字段及精确来源，另一成员不可读canary、原job或连接；模型请求分享更多字段不生效

#### Scenario: Unproven collector identity
- **WHEN** 原child有另一工具或材料pin不匹配，无法证明原工具结果属于已确认collector
- **THEN** 不自动公开该结果并明确缺项，不根据输出自报身份猜测

### Requirement: Original evidence persists without redispatch
系统 SHALL 从已确认停止的原操作采集实际工具输出，沿原运行写入精选证据且同attempt重复采集幂等；UNKNOWN不得重派或伪造失败/达标。

#### Scenario: Capture rollback and restart
- **WHEN** artifact与selection提交前故障，随后恢复原结果步骤
- **THEN** 未完成事务整体回滚，最终只有一套选择和引用，原CLI调用不重派

#### Scenario: Negative result and missing recipe
- **WHEN** 原CLI正常退出但指标未达标，或缺源码/recipe字段
- **THEN** 保留真实负结果及缺项，agent解释与测量分开，不补造commit/命令或声称已验证

### Requirement: Reproducible delivery preserves dependencies
系统 SHALL 仅在应用保存派生成果，不通过通用内容入口暴露绕过来源权限的副本；汇集原目标、全部相关运行事实、精选证据、负结果和剩余问题形成不可变成果修订；每次读取/下载继续核对当前actor与来源权限，不泄漏撤回内容。

#### Scenario: Two member export and withdrawal
- **WHEN** Bob下载Alice共享成果，随后任一依赖记录撤回
- **THEN** 首包字节与精确引用一致；后续manifest正文和下载拒绝，不代理Alice读取，也不承诺远程销毁已读字节

#### Scenario: Generic content cannot bypass derived source withdrawal
- **WHEN** 生成manifest后来源撤回，调用通用内容list/read/artifact及应用目录/详情/导出
- **THEN** 通用入口不存在派生正文/附件副本；应用目录无目标或结论摘要且隐藏不可读条目，详情/导出拒绝，原source遵守原core权限

#### Scenario: Empty source does not grant team visibility
- **WHEN** 项目尚无可共享source且owner生成缺项manifest
- **THEN** 仅owner可读，其他成员目录及详情不获得该私有项目信息

#### Scenario: Bounded complete export
- **WHEN** 选中来源损坏、缺失或总量超限
- **THEN** 完整导出明确失败，不输出标为完整的半包、不执行recipe或获取外部URL

### Requirement: Independent reproduction and continuation
系统 SHALL 提供可独立运行及继续研究的配方和原证据；只有实际复现证明相应环境下结果，不把合成模型、程序自报或hash校验等同科学验证。

#### Scenario: Actual deterministic CLI reproduction
- **WHEN** 第二成员在干净目录只依成果中的源码/依赖/数据/配方运行确定性CLI
- **THEN** 得到事前固定指标，未读取原聊天/私有配置；新尝试使用新身份和预算，原UNKNOWN不重派

#### Scenario: Missing real environment
- **WHEN** 真实模型/GPU/数据或科学容差尚未冻结
- **THEN** 对应正式验收保持BLOCKED，确定性CLI机制通过不解除这些门槛
