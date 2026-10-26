## Purpose

让原研究任务产生的完整约定、决定、条件和证据在明确预算内可靠发布及读取，避免合法正文组合使已停止任务永久无法收尾；同时保持原身份、来源撤回、精选公开范围和独立科学验证的区分。

## ADDED Requirements

### Requirement: Complete bounded publication body
内容发布 SHALL 使用内联 JSON 对象或一个精确正文制品引用，二者互斥；引用正文保持原对象结构与安全数据规则，完整 UTF-8 JSON 不超过既有单制品输出字节预算。原 20 个精选证据附件额度 SHALL 不被正文载体占用，旧内联请求的幂等身份不变。

#### Scenario: Legal Chinese terminal and selected evidence
- **WHEN** 合法 1587 字中文约定与 1900 字停止理由已保存，组合超过内联限制但未超过单制品预算，且已有 20 个合法精选附件
- **THEN** 原完成过程保存并发布完整正文及全部 20 个精选附件；不截断、不换任务或预算，不把载体当新增科学证据

#### Scenario: Genuine body budget exceeded
- **WHEN** 完整终稿确实超过配置的单制品字节预算
- **THEN** 原已证实停止的任务可一次性记录 `publication_failed` 与明确大小原因，原决定、科学 outcome、目标及精选证据保持 owner 可读且受原来源约束；不发后继、不声称发布成功、不将科学 outcome 改写为失败

### Requirement: Original atomic completion and recovery
正文制品、内容引用、领域终态与原结算 SHALL 使用原完成事务；事务失败不得留下孤儿制品或新回执，重试不得重派任务或重复发布。已停止但终稿提交失败的基线原组件 SHALL 保持精确收尾责任；旧暂停组件不得被新版组件替换执行。

#### Scenario: Persisted old decision and rollback
- **WHEN** 基线精确组件的原任务已停止且保存大决定，收尾在制品写入或 publication 写入后故障并再次执行
- **THEN** 失败尝试的制品/事件/发布/terminal/settlement 一并回滚，成功重试仅留一份完整发布，原 task/run/operation 不变

### Requirement: Current-authority complete reads
read/list/正文制品读取 SHALL 先核当前 actor 与完整来源权限，再验证原制品和解封正文；缺失、损坏或撤回不得返回缓存或影子正文。后继、QA、关联、交付取源和 UI 原来源读取 SHALL 保持相同 content 对象语义，各自已有模型上下文预算不因存储格式扩大。

#### Scenario: Consumer and withdrawal continuity
- **WHEN** 授权成员读取可放入既有上下文预算的长中文终稿，随后任一原来源撤回或正文制品损坏
- **THEN** 首次 UI/后继/QA/关联/交付取源得到完整同一正文，后续所有入口拒绝派生正文；大于模型上下文预算的记录仍可完整读取，但不得宣称已送入该模型

#### Scenario: Pagination and export accounting
- **WHEN** list 返回多条制品正文或交付汇集引用正文
- **THEN** list 保持原分页上限，每条正文服从单制品预算；交付把解封后的正文计一次，正文载体不加入精选证据清单或重复导出，不裁剪来源依赖
