# Design

## Context

见 proposal。b6c383a真实PG/密码/Chromium基线复现：ResearchSessionSetup.prepare自动发布的内部定义混入通用创建；普通v2编辑能力另属B。旧9e dirty分页仅作参考，不整合旧工作区。现有 ApplicationService、CompositionService、Composer/Inbox/commandKeys 已提供执行和恢复能力。本片不阻断已有 Auto Research 自由会话的部署与真实模型整链验收。

## Goals / Non-Goals

**Goals:** 应用→任务模板→必要输入/资源→预览→接受→明确启动的一条可验证路径；应用内部定义不误导普通成员。**Non-Goals:** 作者B、资源内页改造、通用分类/迁移/表单框架、全能v2编辑器、新权限/登录/执行引擎、首个默认示例模板。Agno保持3.1.0。

## Decisions

### 一个用途字段，不改变执行授权

在已有 `af_application_states` 增加 `entry_kind`，值为 `template` 或 `application`，缺省 `template`；它仅声明默认发现/入口用途，不参与正文哈希、预算、权限或任务身份。复用项目现有inspect-column/ALTER TABLE模式增加一个column（String NOT NULL DEFAULT 'template'），新库create_all、旧库一次幂等加列；不建迁移框架/新表。旧origin、bootstrap含义不变。

`ApplicationService.create_draft` 增加仅可信Python调用的 `entry_kind`关键字；HTTP普通作者仍默认template，修订继承原值，但沿用旧 `{action,definition,parentRef}` 指纹；只有可信新create的显式非默认声明纳入用途字段，默认create路径也保留旧指纹。已保存revision跨用途标注后以同request重试仍返回原结果，不新增兼容分支。新增内部帮助方法对输入的准确pin核对已存id/version/sha后只标记application；没有公共写端点、不接收credentials。ResearchSessionSetup.prepare和ResearchSetup.publish的新定义明确application。

旧自动生成定义确有当前会话数据消费者，故由两个Research服务初始化时各自读取自己表中已保存的applicationRef，结束读取事务后交上述方法幂等标注（不嵌套持有连接）；core不得读Research表。仅持有准确ref才标注，原记录缺失或id/version/sha不匹配时只返回未标记并记录含ref/原因的warning，不打印正文或凭据；不因目录用途标注阻断Research启动。不得捕获连接/SQL等非预期错误，不猜测、不删除正文。该标注只改变默认入口，research+experiment混合mode的原exact引用和高级能力保留。应用未安装时不擅自推断未标注旧记录。重启不产生新版本、新任务或重放执行副作用，允许上述用途元数据的幂等写入。

旧 `GET /applications`、definitions、inspect、require_current与精确引用开始完全保留，Research ExecutionEditor继续读取旧应用列表筛选兼容native。普通目录不替换这个接口。

### 单一模板读取，过滤在分页之前

新增 `GET /applications/templates?after=…&limit=50`，仅member可读。SQL先按state=published、bootstrap=false、entry_kind=template过滤，再id升序/version降序keyset；返回 `{items: FactoryApplication[], nextCursor: string|null}`，limit1–100。只需这个published用途，不提前增加B的mine草稿分页。cursor只携带此固定目录的id/version边界并验证结构；分页不提供快照承诺，撤回后页允许减少，无越权草稿。

Composer普通选择与新目录使用该投影；高级精确ref/应用来源继续旧路径。自动匹配在无显式application/ref时读取全部符合用途的最新谱系候选，不受前100条草稿遮挡，复用现有评分/ID同分顺序和无命中唯一default规则。显式旧application/ref仍沿原校验，不将目录隐藏当执行拒绝。预览/接受/启动照旧重新校验实际材料与连接。

### 自动匹配先读取模板，再填写其输入

独立审查TE-001复现：goal-only propose在匹配模板有必填schema时先返回422，前端因此拿不到待填写字段。最小补充现有CompositionService的只读 `match_template(owner, goal)`，直接复用 `_input`/`_application`；HTTP `POST /compositions/proposals/match` 仅接收goal并返回完整准确应用定义，不创建提案/方案/命令/任务、不调用模型、不做资源预检。使用POST避免把研究目标放入URL；保留现有member/CSRF边界。评分、ID同分、唯一default规则不变，不加浏览器匹配算法。

自动入口先显示“匹配任务模板”，得到准确模板后复用现有输入/连接表单，用户再点“预览任务方案”；后续请求明确pin该版本，避免填写期间静默换模板。匹配失败保留目标并可重试/返回目录；匹配成功不是预检或启动成功。缺必填值的原propose仍422，不放松schema或把无效输入保存成提案。该行为由真实便携服务+组件/HTTP契约验证，PG/browser仍另验。

### 小型前端旅程

新增平台 `templates` 视图（应用页次级入口），已发布版本列表→准确详情→用此模板创建。只保存id/version路由指针，详情用既有inspect获取正文/用途；不从query猜目标/session。空目录提供返回应用与已有作者入口；读失败单独重试。列表与详情分开读取，浏览器后退恢复已读列表不再次追加当前页；只有明确“更多模板”才追加下一页。元数据/用途不允许时不展示普通创建表单；高级原入口保留。

ComposerSeed增加明确 `kind: 'template'` 区分普通模板种子与原业务来源：模板只固定ref，goal可写；原sourceSnapshot和业务seed继续锁目标。只展示schema声明的输入和必要连接；只有一个mode时显示名称不要求再选；可选材料/预算技术细节折叠。目录可选并不声称资源可用。

缺连接提供现有模型/对应资源入口和“返回这次任务”。在现有Pages中保存这个Composer的临时输入（内存、按owner和模板ref区分），跨资源页回来保留；不持久化凭据或新增通用状态框架。未保存输入刷新/关闭用beforeunload提示，不能许诺刷新恢复未提交内容；已提交提案继续由现有owner pointer/Inbox恢复。返回只带明确模板创建来源，不借旧研究query构造返回；退出换人清空临时输入。

预览、接受、启动分别有单一明确动作；接受后保持同页固定范围但须再次明确开始。重复点击/按键不会穿透到下一动作，依赖现有busy/mutationLock与稳定requestId；UNKNOWN始终核对原请求，不能清空重来。活跃提案/创建历史保持可见可恢复，远端仍不能定时。资源恢复回来刷新连接列表，不默默接受旧预检或更改已接受方案。

### 当前设计指导

沿用已选浅色侧栏。实际读取官方缓存 ui-ux-pro-max `28b3b8d`（字段就地错误、深链/返回/44px触控）、impeccable `6743a34` clarify/distill（工作台≠模板、主动作与细节分层、空态下一步）；不安装/运行脚本，参考不等于验收通过。

## Risks / Trade-offs

- 用途误当权限或全局过滤破坏Research → 保留旧目录/require_current/explicit ref；mixed-mode与旧运行继续回归。
- 初始化标注拿着外层连接再写导致小池阻塞 → 先读取pins并结束事务再标注；真实PG重启/size-one用例验证，无新任务/新版本。
- 资源返回改变原请求 → owner内存草稿只在未提交/允许修订时可改；UNKNOWN/accepted仍按原动作锁定。
- 工作量膨胀 → 只published模板分页，无mine草稿分页、作者编辑B或通用错误引擎；A不作为现有Research部署前置。

## Migration Plan

加列不更改应用正文、历史哈希、任务或凭据。仅Research持有的exact pins标注默认入口。测试在临时旧schema库验证加列与重启幂等，原应用数据仍可读取/执行。回退代码可忽略该元数据列，不删列/数据。合入前继承#164最终main并复核导航冲突；由既有负责人执行full与发布。
