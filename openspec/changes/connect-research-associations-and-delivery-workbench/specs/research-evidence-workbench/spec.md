# Spec Delta

## Purpose

让成员在已确认研究工作台中设置有界关联、核对研究来源并取得真实成果，同时在来源撤回、目标修订与证据缺项时保持诚实呈现，不以可下载或进程结束冒充科学验证。

## ADDED Requirements

### Requirement: Visible bounded association consent and sources
工作台 SHALL 在明确提交的助手配置中显示关联启用及收件上限，呈现当前可读的真实关联与输入出处，并将分析标为agent推断；旧配置不因打开页面而自动增加消费权限。

#### Scenario: First configuration and existing private QA
- **WHEN** 成员准备首次完整助手配置或查看旧私问配置
- **THEN** 首次表单可见默认启用关联及有限上限，须明确提交才生效；旧缺字段配置维持未启用，费用未计量说明持续可见

#### Scenario: Relevant analysis and withdrawal
- **WHEN** 成员打开有关联结果及其来源，随后任一来源变为不可读
- **THEN** 展示真实作者、关系、分析及全部输入依据；重读后整段受保护正文隐藏，不以缓存或少量引用替代授权，不广播或伪造通知

### Requirement: Protected projections never restore old body
工作台 SHALL 将来源不可用作为明确的读取分支，仅显示响应实际保留的身份和事实，不读取缺失字段、不恢复旧正文、不把原终态标记当新的停止证明。

#### Scenario: Project and run source is unavailable
- **WHEN** 项目目标不含agreement、实验不含hypothesis/conditions/operation，或轮次仅含原终态存在标记
- **THEN** 页面不崩溃，显示来源不可用与原ID/版本；隐藏目标编辑、旧分析及产物入口，不推定已失败、资源已停止或允许重派；仍可核对原状态及沿现有授权取消边界处理

#### Scenario: Owner or selected record changes during read
- **WHEN** 成员、关联或成果选择改变后旧请求才返回，或当前读取失败
- **THEN** 旧正文/出处不得填回新视图；拒绝或撤回时不继续显示此前派生内容

### Requirement: Evidence selection survives explicit goal revision
工作台 SHALL 在约定确认前显示精准CLI材料及metrics/source/run_recipe有限字段选择，修订目标时保留未改动的原选择；资源、预算和原操作生命周期继续由既有执行契约约束。

#### Scenario: Revise an active research goal
- **WHEN** 成员在原运行未终结时修改目标、评价或停止条件
- **THEN** 新旧版本保留，原evidence与执行配置不默默丢失；保存与确认不声称已停原运行或重置预算，按服务端真实可用性沿原事件续接而不另建替代操作

#### Scenario: Missing or incomplete evidence configuration
- **WHEN** 没有可证明的CLI材料、缺少选定输出字段，或旧约定没有evidence
- **THEN** 明确缺项并提供既有材料/资源入口；不能默认公开整个输出、补造配方或将模型正文当测量结果

### Requirement: Honest source-bound delivery
工作台 SHALL 允许作者按当前目标版本生成可恢复的不可变成果，允许当前有权成员查看manifest与下载，保留缺项、负结果、出处和未验证级别，不承诺已验证可复现或已取得不存在的剩余问题记录。

#### Scenario: Create acknowledgement is lost
- **WHEN** 成果生成已接纳但响应丢失，随后刷新或重新进入
- **THEN** 保留原requestId与payload并恢复原成果，不自动生成新成果请求；版本冲突保留输入并要求明确处理

#### Scenario: Incomplete manifest and authorized download
- **WHEN** 成果含missingEvidence、remainingQuestions未提供或未终结原轮次
- **THEN** 明显标注不完整与具体缺项；下载只交付服务端真实包，不将下载成功、producer_declared或进程completed称为科学验证

#### Scenario: Revoked or failed download
- **WHEN** 当前来源授权失效、下载出错/超限，或下载期间切换身份
- **THEN** 不输出可误认成功的包，不恢复旧manifest，不借作者权限下载；不伪称完成独立artifact哈希校验，不承诺销毁此前已下载字节

### Requirement: Existing platform journey remains intact
工作台 SHALL 沿既有平台首页、登录、资源入口和受限URL导航提供关联/成果深链与返回，不新增认证或执行控制链。

#### Scenario: Two members follow research to delivery
- **WHEN** 两成员在桌面和窄屏完成配置、研究、关联、修订、结束及成果读取，并刷新/退出重登/往返资源页
- **THEN** 当前身份与原记录一致、焦点可操作、平台首页仍独立；合成模型浏览器证据不代替真实模型团队价值或GPU验收
