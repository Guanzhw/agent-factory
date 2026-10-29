# Verification

基线 `8a7c0fc9393bf4c1ff824b2f75cc7e96e991d89e`；产品候选 `b8dc6df71de729904adba611fceea49a1d273df1`，tree `2caf1bb8faff00e5def81f1f56624ef4806451c3`。随后仅整理本记录、任务进度与截图。2026-10-29 UTC；准确最终文档head的full CI和发布另行核验，不以本记录宣称合入或部署。

## Result

本片完成“应用 / 我的任务 / 我的资源”的日常入口、创作维护次级入口、实际资源分类，以及从独立Research补模型后回到原会话/项目输入。分类保留表单挂载，模型保存和返回不执行研究；另一模型设默认不会清掉当前编辑，单次输出额度保留。秘密仅在表单内存，退出/认证失效清理私有草稿。

原 `a8ef64c` 独审发现两项P2：项目视图草稿盖过明确的另一个setupId；通用页面硬编码Research并丢失connections返回。`b8dc6df`按实际编辑目标区分草稿，由Research壳注入最小返回信息，并恢复来源回跳。原反例保留，独立复跑通过。远端资源刷新复用原effect，保留输入，无新路由/表单框架。README过时的“Research已移除”说明已单独核对并纠正为显式可选装配。

## Checks

- 作者 `npm run check`：618测试/58文件、类型/lint/core构建通过；Research构建通过，既有chunk大小提示保留。113个前端模块边界检查无违规；官方production/full依赖审计均0，未新增依赖。
- 非作者完整累计审查与简洁性复审通过；最终增量独立7文件93测试通过，另有项目反例和28项独立补充检查。均为组件/协议检查，不能替代下面的实际浏览器结果。
- 开发辅助Go请求返回429，没有回答，未重试或切换provider；未将它记为模型审查通过。

## Real Browser Coverage

Chromium151.0.7922.173、Linux；隔离PostgreSQL、真实临时密码登录及API。全部模型调用为0，没有创建外部凭据、SSH/GPU操作或研究任务。

| 范围 | 已验证行为 |
| --- | --- |
| 1440/390主流程 | 应用与独立Research往返；缺模型草稿、就地字段错误、真实模型配置保存/设默认及输出额度8192、双击不重复configure、回原输入并刷新；另一模型设默认保留未提交输入。 |
| 1440/390项目 | 执行/准备输入跨资源页、后退前进、刷新、另一项目隔离；没有自动保存项目、发布或启动。1440另查两个真实setupId明确入口及旧connections返回。 |
| 1440/390身份清理 | 实际退出，及移除测试cookie后真实接口401，清理项目/会话草稿，下一成员看不到原私有输入。 |
| 390丢回执 | 故意丢弃已落库的configure响应，沿原GET恢复，只继续尚未发送的default，没有替代configure。明确为网络故障注入。 |
| 390拒绝 | 故意将测试POST输出额度改为0，真实服务422原样到达UI，不报成功/不离开，可修正后明确保存；原已保存模型保留。明确为请求故障注入，非mock响应。 |
| 320 | 关键字段错误、返回与无横溢；未重复全部项目组合。 |
| 普通core | 同候选独立普通build与core服务，真实空目录、三入口、Research按钮不存在且API404。 |

首次明确403/422拒绝与已发送请求的GET403/404失败沿用原协议，spec的原笼统措辞经独审明确修正。后者仍保留原标识；不能把当前阶段拒绝说成此前已成功阶段未发生。

原QA定位/时序失败保留：标签包含帮助或文本值、未展开输出设置、注入请求尚未完成就断言。只修正QA定位/等待，没有改值或normalize空白。一个原campaign完成1440后在390失败，报告只使用其已完成的1440断言；390/320、core及422另有成功记录，没有把整轮FAIL改写成PASS。所有服务、生成测试库和scratch已清理，共享PG保留。

## Screenshots and Evidence

以下均为此产品候选的真实浏览器PNG，含隔离测试标记，无真实凭据。项目恢复字段和setup名称有逐字DOM/API证据，但在其他保留截图中位于屏外，不以那些图声称已完整展示。

- [资源入口](../../../docs/images/daily-research-entry/desktop-resources.png)
- [手机就地字段错误](../../../docs/images/daily-research-entry/mobile-field-errors.png)
- [手机真实保存与返回提示](../../../docs/images/daily-research-entry/mobile-saved-return.png)
- [普通core空目录](../../../docs/images/daily-research-entry/core-empty-catalog.png)

审查目录 `/workspace/design-audit/daily-research-entry-20261029`：`code-review/review-b8dc6df.json` SHA256 `7bb90ee8162111289c4a06cb763baa12ae4232467c82c02caaa05594b36e7fda`；`browser-qa/verification.json` SHA256 `29e404c22a946b3a96d97634ac4c1598bae9d18d1d8269fcc7018a8572cc62d3`，保存各场景、原失败及源码/构建hash。

沿用已只读核验的官方[ui-ux-pro-max指导](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/28b3b8dee8c976df4fa3e94aed4e092ad43fcb03/.claude/skills/ui-ux-pro-max/SKILL.md)落实就地错误、焦点、手机触摸和一致导航；[impeccable clarify](https://github.com/pbakaus/impeccable/blob/6743a347db6229848348024388033e830ae4af42/skill/reference/clarify.md)与[distill](https://github.com/pbakaus/impeccable/blob/6743a347db6229848348024388033e830ae4af42/skill/reference/distill.md)用于三日常入口、次级创作入口、明确返回与保存结果。未安装这些技能或执行其脚本，技能使用本身不等于验收通过。

## Limits and Next

未测真实模型兼容/质量、GPU/SSH、目标硬件30会话容量、用户可达部署；原回执GET403/404浏览器端到端反例、全部外部资源表单和项目目标版本变更的单独浏览器场景未跑，组件证据单列。当前无正式云端预览地址，loopback不等于用户部署。

下一片继续任务结果/失败与原请求上下文、停止运行和暂停计划的区分；随后处理模板来源分类/作者路径、存储和历史入口。内部Research运行定义不能冒充普通模板，任务没有scheduleId也不能靠planId猜计划来源。本片不代表全站整改或团队研究产品已完成。
