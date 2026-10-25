# Spec Delta

## Purpose

通过已有研究事件、稳定助手与原生执行，将当前有权读取的研究记录定向关联起来，明确区分agent推断与实测事实；让已确认研究保留来源如何影响决定和原动作的证据，而不是以消息数量或静态引用冒充团队经验复用。

## ADDED Requirements

### Requirement: Explicit bounded association configuration
应用 SHALL 在首次完整助手资源与有限预算配置中明确启用关联，随后复用原QA endpoint/scope自动处理有关事件，无逐条发送或发布审批；旧仅私问配置不得自动获得新消费权限，BYOK token/费用未计量必须明确显示。

#### Scenario: Existing configuration and unsupported hard cost limits
- **WHEN** 旧QA配置未明确启用关联，或用户提交当前BYOK不支持的token/金额硬上限
- **THEN** 前者不创建自动订阅/消费，后者明确拒绝；不默选模型、不续额、不切换platform-paid


#### Scenario: Configured assistant automatically handles research events
- **WHEN** 双方完成启用关联的助手资源与有限预算配置，有关研究事件发生且接收者离线
- **THEN** 自动检索/准入/分析/记录，不要求逐条批准或手动发布；默认永不启用、停在资源未配置或全部沉默不能被当作完整旅程与A08/C03通过

### Requirement: Selective original research event delivery
应用 SHALL 仅由精选start/terminal事实触发有界相关候选，复用P3 outbox/原准入；收件规则与上限必须在运行前固定。

#### Scenario: Relevant versus irrelevant records
- **WHEN** 原研究事件遇到相关、无关、本人、私有或未启用助手的记录
- **THEN** 只有符合已声明规则且双方当前可读的少数目标入选；无匹配零发送，不全员广播兜底，不读私有项目找兴趣

#### Scenario: Duplicate and restarted event
- **WHEN** 同一content事件或原delivery重投/重启
- **THEN** 保留原选择、event/message/task/allocation身份，不扩大候选、不重复计额或再派发UNKNOWN

#### Scenario: Budget exhaustion or expiry
- **WHEN** 接收者原操作scope耗尽、到期或配置已停用
- **THEN** 后续新准入被拒、模型/训练调用不增，原运行和历史回执仍可按现身份恢复

### Requirement: Evidence-based tool-free association analysis
事件consumer SHALL 从原task验证的event及匹配记录取输入，保存完整实际依赖，使用固定tool-free模型判断相关性和条件；分析不得伪称实验验证。

#### Scenario: Useful relationship with different conditions
- **WHEN** 两记录表面相关但实验条件不同
- **THEN** 分析显式说明条件和来源并标agent_analysis；不更改原记录，不把“相似”当作已验证可迁移的结论

#### Scenario: Unrelated or malicious sources
- **WHEN** 模型判定不相关，或原证据/实际provider要求train、CLI、MCP或remote调用
- **THEN** 不相关不创建用户关联通知；非法工具调用有界失败且零GPU/child派发，不无限模型循环，不把失败记成功分析

### Requirement: Source-dependent derived publication
应用 SHALL 对所有实际peer输入及派生输入影响的模型/下游字段保留完整原来源依赖并集，读权逐源委托core；不得将hypothesis/conditions/goal/child output等复制到不检查依赖的team content并称作独立事实。精选正文仅存一次source-bound core content；研究运行投影在来源不可读时只允许opaque IDs/固定状态。

#### Scenario: Uncited source withdrawal
- **WHEN** 模型读了A/B但只显示引用A，B在提交或读取前撤回
- **THEN** 整段派生正文和引用不可发布/读取，不能仅删B链接；原runtime事实与原操作身份保留，无新派发

#### Scenario: Another team member reads an association
- **WHEN** 第三位成员读取关联或项目下钻分析
- **THEN** 必须当前可读全部原来源，否则不返回正文/隐私引用；不借关联取得原作者任务/私聊/凭据权限


#### Scenario: Canary copied through experiment and downstream output
- **WHEN** 输入来源B的canary进入模型hypothesis/conditions/goal、child返回值/产物及project ending，模型最终只显示引用A，随后B撤回
- **THEN** start、terminal、project ending、experiment和关联所有应用投影不返回canary、派生正文或产物入口，只保留safe opaque IDs/固定状态；原task/operation停止事实仍可读，不删除或重派原效果

#### Scenario: Next round inherits original source union
- **WHEN** 后继轮次只读取前轮摘要、原child输出或一份association，或者修订目标后沿用这些结果
- **THEN** 完整继承其全部原来源依赖与本轮新来源的并集；不得因换id、压缩、少引用或新goalVersion清除依赖；任一来源撤回阻止新的模型/实验消费，原UNKNOWN观察取消仍保留

### Requirement: Actual source to decision to action trace
仅实际使用peer证据的研究轮次 SHALL 持久其原input、适用性选择与原实验动作关系；未使用peer证据的历史轮次保持既有语义。

#### Scenario: Use or independently reproduce a prior result
- **WHEN** 已确认研究模型接触实际来源并选择采用、复现或不适用
- **THEN** 来源访问、条件理由及真实执行goal/operation可关联；有理由复现允许，不能仅凭引用/自称复用/消息数通过价值验收

#### Scenario: Revoked source before a new experiment
- **WHEN** peer来源在context之后、原attempt准备事务准入之前撤回
- **THEN** 阻止新动作；准备事务在原admission锁下校验完整依赖并固化输入/意图。若该原准入先于撤回完成，允许已授权原操作继续；后继round重新当前read。已存在child/UNKNOWN仍按原身份观察/取消，不能因关联重新派发，也不能让私问事件自动开始研究

### Requirement: Honest independent acceptance layers
验收 SHALL 分开确定性路由/权限机制、真实浏览器和真实模型团队价值，不以合成脚本或全部沉默代替C02/C03。

#### Scenario: Paired real research evaluation
- **WHEN** 执行事前冻结的有经验/无经验对照及不相关/过时负对照
- **THEN** 核对真实来源、适用性决定和实际动作差异；隐藏oracle不给被测模型，无差异按原标准如实失败，不调通过线或强迫科学指标提升

### Requirement: Direct original evidence and one authorized publication
研究context SHALL 在没有association时仍检索当前可读、相关的原团队研究记录；使用现有词项筛选及50候选/8显示/16KiB边界，不另建检索框架。完整依赖并集不受显示边界截断。精选派生正文 SHALL 只存一次source-bound核心publication，由core所有读取/附件/回执路径核原来源；研究运行投影仍只在来源可读时显示富字段。此项替代未发布的影子正文回填方案。

#### Scenario: Original evidence without a prior association
- **WHEN** 团队有一条相关原记录、另一条无关记录，未有任何association
- **THEN** 研究模型实际接收相关原证据，并将其原ID关联到决定和真实child goal；无关记录不进入，撤回先于新attempt准入时零新派发

#### Scenario: Project writes preserve admission-first order
- **WHEN** project create回执或change与原round准备/来源读取并发
- **THEN** 两者均先admission后research namespace，双向barrier验证无锁环，不在_protect内部补锁
