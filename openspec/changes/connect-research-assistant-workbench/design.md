# Design

## Context

基线`f2dd047`，实际契约在`applications/research/{assistants,setup,projects,public}.py`；上位规范为`add-research-assistant-qa`，验收映射`docs/plans/research-platform-acceptance-contract.md`的A02/A03/A05及B01/B02。已确认工作台的布局、平台导航/auth、资源往返和`useResearchCommand`保持复用。此补充只将已有QA能力接到界面，不重做样式或更改后端契约。

## Goals / Non-Goals

**Goals:** 用户可创建稳定研究助手、明确发布固定QA定义并设置有限操作额度；选择一个助手私密提问，读取原回答及其当前可用的输入依据；刷新/换成员不重复执行或泄露旧回答。

**Non-Goals:** 新聊天历史服务、本地答案档案、任意工具composer、模型自动选择、研究训练/远端调用、第二认证/轮询worker。自动相关性推荐及研究source→decision→action仍属于后续P7，不以目录/私问冒充已完成。真实C/D验收不由合成UI测试解除。

## Decisions

### 控件及路由

- 保留平台首页→AutoResearch→项目→返回平台；研究右侧栏显示当前成员的稳定助手身份/可用状态以及“设置我的助手”。没有助手时仅显式“创建我的研究助手”，GET不创建。
- `researchView=assistant`在现主内容区显示助手设置，窄屏沿现布局堆叠；返回工作台保留原项目上下文。研究QA草稿单独用`researchQASetup`标识，不能与实验`researchSetup`混用。
- 已有`researchView=team`显示分页助手目录（姓名、本人/同事、可问答状态），只向用户明确选择的一位助手发送。目录没有主题专长字段，不编造“最相关”排序。其当前职能标明“向团队助手询问经验”，不伪造团队记录浏览器。
- 指定助手用`researchPeer`，已发送问题用`researchQuestion`保留原message ID。沿现`WorkspaceNavigation`解析有限值，不另建router。右侧栏/窄屏现有研究助手抽屉显示单个原问题，不画伪聊天时间线。返回平台/应用新入口清除这些应用参数；资源往返保留来源。URL只放ID，不含问句、回答或凭据。
- 项目创建选择当前owner的`researchAssistantId`，未创建可留空；旧`assistantId`只读保留原endpoint含义。新字段不从旧值猜测，已有项目不隐式改写。

### 真实接口映射

| 动作 | 实际接口与行为 |
| --- | --- |
| 个人助手读取/创建 | GET `/research/assistants/me`返回`{assistant:null|projection}`；POST `/research/assistants {requestId}`返回稳定projection，配置revision及qa状态来自后端 |
| 候选与QA草稿 | 复用GET `/research/setup`实际model/connection候选；POST `/research/setup/qa/drafts {requestId,name,modelConnectionRef,budget}`，budget为既有core执行上限；不选择实验环境/工具 |
| 草稿恢复与发布 | GET `/research/setup/{id}`；POST `/{id}/publish {requestId}`。显示private preview，只有published真pin才可进入助手配置；校验预览mode=qa以免误用实验配置 |
| 确认操作额度 | POST `/research/assistants/me/configurations {requestId,expectedRevision,applicationRef,connectionRefs,budget:{caps,perQuestionCaps,deadline}}`。总问题次数、工具操作额度、每问上限和截止时间显式填写；每问rounds=1，tokenLimit/amountMicros/currency均null |
| 指定助手 | GET `/research/assistants?after=&limit=`，显示`id/ownerId/displayName/qaAvailable`与分页，不尝试读取同事配置或模型连接 |
| 私问与读取 | POST `/research/assistants/{id}/questions {requestId,text}`返回core原消息投影；GET `/research/assistant-questions/{messageId}`只读。`delivery.state/taskId/runId`是原准入/执行投影，不表示回答已存在 |
| 输入依据 | `reply.state=available`才显示text和contentIds；标“输入依据（包含模型实际读取的全部记录）”，不冒称逐项引用。点击先核对原问题仍available，再GET `/application-content/{id}`，显示实际记录的来源/内容，不借同事taskId读任务 |

所有调用沿`factoryRequest`及expectedOwner；没有新的token、凭据字段或auth状态。模型选择仅使用真实可用connection.ref（不是registrationRef）；缺项链接现资源页。设置/发布/确认不会在UI自动发送测试问题。配置页和问答页明确显示“操作额度受限，token/费用未计量”，不显示推算费用或虚构剩余额度。

### 原请求与当前读权

创建、QA草稿、publish、配置CAS及私问复用现owner-scoped pending命令语义；key区分owner/action范围及peer/setup ID。同requestId+payload恢复，408/network/5xx不换键；配置冲突显示后端原因，要求重读revision后由用户确认，不能自动重试新配置。收到成功写回执后先保存message ID到路由，后续GET失败不能导致新发问题。配置/提问使用POST的直接回执，不把后续读混入写成功判定。

只在内存显示回答，不把成功问答或来源正文写入sessionStorage。刷新以URL原messageId重新GET；未确认命令仅保留恢复所需的原payload，按owner隔离。首次输入页面是空表单，不从固定句子生成回答。现后端没有研究问答历史列表，不额外构造历史服务；用户可通过原问题URL重读。

本单元用明确“核对原问题”读按钮并在页面重新获得焦点时重读；不引入无限后台轮询。重读开始清除旧回答/来源，读失败显示错误不保留旧正文。`reply:null`显示尚无回答与原delivery状态，不推断成功；`source_unavailable`隐藏整个派生答案及输入依据，不仅移除一个链接。来源读取403/404时同样隐藏缓存并要求核对原问题。此保证重新读取时当前权限，不承诺追回用户已读内容或即时推送撤权。换owner卸载原视图并清空内存。

## Risks / Trade-offs

- 没有历史列表 → 只提供原问题URL，不假装完整聊天产品；未来历史能力另按真实API扩展。
- 手动核对需要一次操作 → 明确按钮/状态并在恢复焦点重读，避免当前小单元增加定时器生命周期与后台流量。
- UI不能保证费用硬限额 → 固定后端accounting说明；不提供无效token/金额输入，不把null包装为免费。
- 来源通用content schema可能不同 → 显示当前真实来源信息与结构化内容，不将过程完成称科学验证；不开放任意HTML或远端图片执行。

## Migration Plan

无数据迁移。新前端使用新增稳定助手字段和已有API，保留旧项目endpoint字段。生产core默认无研究应用时不添加助手入口；QA后端未装配的请求失败按真实错误展示，不回退demo。独立分支实现，冻结125不改。
