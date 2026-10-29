# Verification

2026-10-29。基线 `8ff92173bc6707cfb0bb7604b759a58d1c3c0eb7`；产品候选 `7023a993f1745f8394fdd8f04cd9818011b93f5c`，tree `776c7572ff222379c48d3dfa1115f32a2ed5053c`。随后仅整理本记录、任务进度与原始截图。代码独审与下述限定用户旅程通过；最终文档 head 的 full CI、发布和主干核验另行完成，不表示已部署。

## Full CI failure and diagnostics

`455506f4110d53d130772a800552b59f7480d9b8` 的 [full40806050019](https://github.com/Guanzhw/agent-factory/actions/runs/40806050019) 失败：PostgreSQL 全量执行、完成核验和汇总失败，其余五个 job 成功。普通 Checks API 未给出失败测试 ID；十条源码错误注解与此前成功的8ff full完全一致，不能据这些负向fixture注解判断本次根因，也不因此记作偶发通过。原候选独立本地完整复现进行中，发布暂停；未读取被拒的原始日志/产物。

诊断补丁仅把 `check_python` 既有用例ID/转义traceback注解复用到 `check_postgres`；没有 unittest failure/error 但 required acceptance 未通过时显示既有摘要。测试集合、期限、accepted、退出码和产物语义保持，后续新运行的诊断不回写旧失败。33项无数据库 runner/CI/profiler回归通过，包含两入口的合成失败/错误、非Actions不输出、required skip仍失败；测试捕获这些合成错误注解，不让它们泄漏到正常CI。诊断补丁仍须独立审查与准确新head full；不能称旧根因已修。

## Behavior

“我的任务”先显示状态、真实失败、待处理要求与已有产物；当前任务的原回执在操作旁，读取详情失败仍能核对。UNKNOWN 不自动重发。研究和计划的明确入口保存来源，返回只读取原记录；直接链接或不匹配来源提供通用返回。暂停后续计划与停止本次执行保持独立，工作流待输入和后代停止范围没有隐藏。

没有新增后端、依赖、角色、路由或恢复框架。通用任务没有所有应用的最终回答协议，因此不把工具失败强改为任务失败，也不把 completed 称为目标成功；完整研究答复从明确返回入口查看。

## Review and Checks

- 规划 `25f4091` 经非作者独审；旧 `8ff9217` 的真实基线先复现了“工具 exit 3、任务 completed、无产物，详情没有研究返回入口”。旧基线仅证明问题，不代替新候选验收。
- 非作者在 `13fe951` 复现计划 A 的手动刷新迟到覆盖已选 B。修复复用现有读取生命周期，丢弃过期读取/预览/忙碌状态更新；已发出的变更仍核对原请求，UNKNOWN 保留。原失败反例字节不变，在 `7023a99` 独立复跑通过；相关 79 项组件回归通过，完整累计 diff 与简洁性复审无阻塞。
- 作者最终 `npm run check`：60 文件/646 测试、lint、类型及 core 构建通过；Research 构建、113 模块边界、OpenSpec strict、diff check 通过。官方生产/全依赖审计均零漏洞。已有大包 warning 保留，没有为此新增构建架构。
- 原 CI configured/bind-loss 两场景在锁定 Chromium 145.0.7632.6 通过，属于合成 API 浏览器检查，不是真实 CLI/MCP。开发辅助 Go 请求返回 429、无回答，未将其算作模型审查通过。

## Real Browser Acceptance

真实临时密码、隔离 PostgreSQL、浏览器和本地进程；全部最终运行的源码/构建匹配同一 `7023a99`。成功研究路径含 8 次 loopback SCRIPTED HTTP 请求，计划路径另有 1 次本地 FixtureModel 调用，外部模型/Go/GPU/SSH 均为 0。计划测试显式安装测试应用，与普通 Research 装配分开；没有产品 demo 模式或模拟登录。

| 用户路径 | 实际结果与边界 |
| --- | --- |
| 研究 → 原任务 → 原研究 | 1440/390/320 通过；真实命令 exit 3、native completed、无产物分别显示，返回同一会话读取失败说明和命令输出。刷新/前后退零写入。1440/390 的直接链接和错误来源 taskId 使用通用返回。 |
| 换用户与空态 | 真实退出、另一用户访问旧任务得到 404，原目标不显示；点击“返回我的任务”后可从本人空态进入应用。未声称侧栏点击自动清掉选中任务。 |
| 手机停止 | 390 两次触碰只创建 1 POST/1 ControlCommand；原父进程消失、后代 Z 非运行，native 父子 cancelled，effect CANCELLED/stopped=true。清理未发停止信号，不声称僵尸已回收。 |
| 丢回执后恢复 | 真实 POST 202 提交后故意丢弃浏览器响应并暂缺回执 GET。恢复读取得到同一原 ID 的 STOP_CONFIRMED，仍仅 1 POST；实际进程停止发生在清理之前。明确为故障注入，不证明远端未知操作恢复。 |
| 暂停计划与本次运行 | 暂停后原生等待输入任务仍 paused、问题可见；独立取消后返回/刷新原计划仍暂停。明确恢复后仍只有原 1 task/occurrence。另一用户读取计划、历史和任务均 404；此例不冒充运行中 shell 停止证据。 |
| A 刷新迟到后已选 B | 暂存 A 的真实 GET 响应，后退选择 B，再释放 A，B 名称、cron、历史和 URL 均未被覆盖。仅延迟传输，无伪造响应内容、无写入。 |

旧 QA 失败完整保留：标题/侧栏路径假设、浏览器路由处理前同步轮询、误用另一接口的 200 代替通用命令的 202。只修正明确路径、事件等待与实际协议，不放宽原 ID/写次数/进程断言。首次丢回执尝试由清理 SIGTERM 结束，因此仍为 FAIL。旧 `13fe` 结果不改写成新版本通过。所有自有服务、worker、scheduler、私有库与临时目录已清理，共享 PostgreSQL 保留。

## Screenshots and Evidence

以下原始 PNG 均由验证者与协调者实际查看，标明隔离合成测试数据，无真实秘密：

- [桌面任务结果与返回](../../../docs/images/task-outcome-journey/desktop-task-return.png)
- [手机返回研究的失败说明](../../../docs/images/task-outcome-journey/mobile-research-failure.png)
- [手机原停止命令确认](../../../docs/images/task-outcome-journey/mobile-stop-confirmed.png)
- [手机返回仍暂停的原计划](../../../docs/images/task-outcome-journey/mobile-plan-paused.png)

审计目录 `/workspace/design-audit/task-outcome-journey-20261029`：`code-review/review-7023a99.json` SHA256 `23776aee081871d29bef09cefdf8c8e400aaf294bb365252ae5b168956e3c264`；`browser-qa/verification-7023.json` SHA256 `4894f88ce86b3525153493bce05d18c47ea8a58d590b9562d534af9d1f0a4195`。丢回执恢复的一张取景错位图片未选用，不作为视觉证明；DOM/原 GET 证据与正常停止确认图片分别保留。

## Limits and Next

本轮未重验全部分页、native failed 与罕见工作流状态组合，不证明真实模型质量、实体手机、Windows shell、GPU/SSH、完整 OS 隔离、30 会话容量或用户部署。组件反例与此前运行证据分层保留。下一阶段继续模板真实来源/创作、资源工具和凭据内页、维护子页与可部署验收；本片不代表全站整改完成。
