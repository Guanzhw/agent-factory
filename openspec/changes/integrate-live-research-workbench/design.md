## Context

已确认布局来自冻结2fbc24c，包含独立平台入口、研究侧栏、项目区与助手区。正式入口为web/research-composition.tsx；底座Workspace提供applicationView、身份、错误/退出busy及既有URL导航。当前后端projects稳定；固定pin原生研究round/record契约由并行后端任务完成，本次不得将未冻结字段作为已验收接口。

## Goals / Non-Goals

完整研究旅程接真实数据，保留用户空间/权限、目标历史、原执行身份和科学结论边界。不是复制demo数据，不另造auth/router/controller，不重写native执行或把原生completed作为研究达标。

## Decisions

1. 同应用live目录拥有布局、读取与呈现，正式composition复用平台slot及资源返回标记。独立平台入口清空project；全局资源无research标记时不劫持返回。未知项目呈现读取错误及返回入口。
2. GET projects分页绑定真实标题/state/currentGoalVersion；draft为待确认、ready仅约定已确认、ended为研究结束。未读取全部页不显示虚假的全量项目数。空列表提供创建及现资源入口。
3. GET project展示当前版本与历史agreement；POST goals/confirm/end使用expectedVersion，409只提示刷新并解释，不自动覆盖。更新目标时保留未编辑execution配置，防止简单表单抹除执行绑定。结束文案说明scope阻断不等于在途操作已结束/资源已释放。
4. 创建和领域变更复用现owner+project scoped sessionStorage原request+payload恢复；408/网络失败/5xx/无效响应保留原请求，切换owner不泄漏。抽取既有hook而不复制恢复状态机。
5. start只在实际服务端available与当前已确认版本下可用，保留原request。202为准入回执，UNKNOWN读取原运行记录而非创建新键。稳定首轮experiments与后续固定pinround契约在接线前明确区分，禁止猜测兼容或静默降级。
6. 助手区先呈现真实关联助手及当前约定/进度来源；无消息接口不展示会返回模板的输入框。存在响应时显示来源record/task/goal版本与agent_analysis标识。团队记录只取限定公开schema，不能将整个项目/凭据作为共享内容。没有指标数据不绘制假曲线；没有结论不填“已达标”。
7. 复用选定布局的颜色/尺寸/图标和窄屏/焦点行为，但正式组件不得import research-demo的数据/行为。presentational样式可在同应用复制并收敛必要选择器，不加UI框架。真实数据的长文本、空/错误/UNKNOWN是必要视觉状态。

## API map and dependencies

| 行为 | 当前接口 | 接入约束 |
| --- | --- | --- |
| 项目列表/详情 | GET research/projects, projects/{id} | owner隐含当前session，分页保留 |
| 创建/修订/确认/结束 | POST projects, goals, confirm, end | 原requestId+expectedVersion |
| 可选助手 | GET assistants | 仅owner启用项，不创建身份旁路 |
| 首轮/原运行 | POST start, GET experiments | 待固定pin新契约冻结后对齐，不把202当完成 |
| 轮次/证据/团队/问答 | 并行后端定义 | 按实际公开契约补入本表，再实现和验收 |
| 模型/连接 | 现ResourceCenter/Pages | 复用平台真实资源流程，无秘密展示 |

## Risks / Trade-offs

后端轮次契约未冻结前，不能宣称完整自主研究已接通；项目路径仍可独立完成。布局确认不等于真实交互或模型验收；合成测试不解除真实C/D门槛。独立review检查完整diff、重复状态机及无消费者抽象。

## 冻结轮次接口接线（后端bb999e5，待集成验收）

`GET projects/{id}/experiments`原生固定pin返回items[].attempts（operationId/operation nullable）与rounds[]（id/goalVersion/taskId/decision/terminal/terminalRecordId/continuations）。旧首轮记录保留items[].attempt.execution；这是明确的领域旧记录，不假造新round。decision/terminal/record均可为空。terminal.verificationStatus=unverified；decision只作agent分析，即使outcome=met也不改称已验证科学结论。operation.observation.state与closed区分原操作结果/是否关闭。运行taskId只导航现core任务页，不造第二inspect/cancel控制链。

POST start沿原requestId/expectedVersion返回准入或续接事件收据。UI继续复用原命令恢复，收到收据后读取原project/experiments；读后失败仍保留同键意图，不生成新键。无运行数据时展示未建立运行，不绘图。原生实验终态/后继仍有后端恢复故障在独立诊断，不能将前端合成fixture当其通过。

## 已发布执行配置

项目先建立研究约定，再从core现applications列表显式选择发布版本和mode；材料选项只取该mode允许的固定pin，资源只取现有可用连接并按kind/capability筛选。deadline与每轮caps由用户填写，不预设费用/资源，不输入秘密，不创建第二composer预检。保存通过同goals命令追加待确认版本；后端固定pin及已冻结承诺仍是权威，任何拒绝清楚显示。初始无发布应用时指向现应用管理/发布与资源入口，不虚构默认研究定义；后续研究模板由应用setup集成提供。

## 研究执行配置 setup 接入

在同一正式应用中用可视表单读取GET research/setup候选，model必须选择实际可用connectionRef（不能把registrationRef/reference当连接）。环境与工具连接由候选实际kind/capabilities限制；缺环境/模型绑定/工具清楚阻断且不假填。POST drafts只保存private intent+preview，applicationRef=null不作为已发布定义；成功后researchSetup URL指针保留owner可读GET/{id}刷新恢复。用户检查选择及预算后显式POST publish；仅其成功真实pin交给约定执行配置，仍需填deadline/perRoundCaps并确认新版本。

两个实际consumer（project mutation与setup draft/publish）共享同应用轻量命令恢复hook；不扩成core通用状态机。原owner+request/payload在HTTP408/未知应答时保留，同键恢复；不通过新的requestId重发发布。资源页往返保留researchSetup/project，平台应用入口清空这些指针。
