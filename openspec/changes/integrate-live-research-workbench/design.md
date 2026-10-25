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
