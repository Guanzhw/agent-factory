# Verification

## Scope

本片交付人工从原研究会话向同事助手提问、B 既有 QA 离线执行、原问题核对/接续，以及 A 选择回复后开始下一轮。Agent 自主发问、私人回复通知和自动采用属于紧接续片，未在此片完成。

基线：main `0acb41e02ac9453bd8c5be751cecf13dc04ef02f`。产品提交：`66f39158a865916a6c2b4389ec9b9a37d442a402`；后续交付提交仅增加文档与验收截图。依赖 PR #152 的 full 40679087337 和 main 40688237438/40688238131 均通过，merge tree 与已验 head 一致。Agno 仍固定 3.1.0；无新依赖、产品 demo、身份或凭据迁移。准确交付 head 的 full 与最终发布状态以 [PR #153](https://github.com/Guanzhw/agent-factory/pull/153) 的核验记录为准，尚未运行的 CI 不由本文件预先宣布通过。

## Evidence boundaries

| 层 | 已取得证据 | 不能据此声称 |
| --- | --- | --- |
| PostgreSQL / 会话保护 | 作者回复采用及既有上下文回归 42 项通过；采用与取消锁序、撤权隐藏引用副本、主请求/摘要/工具拒绝、新旧请求兼容 | 完整 OS 安全隔离、真实研究质量 |
| PostgreSQL / 消息关联 | 原子消息/预算/会话关联、并发幂等、事务回滚、丢 ACK、原任务 UNKNOWN 不重放、跨用户及旧独立问答不可改绑 | 普通查询能恢复执行或可更换原预算 |
| 原生 QA | 实际 PostgreSQL、Agno 原生队列、脚本 provider：B 无浏览器参与地回答，A 原会话读取并采用；撤权后引用隐藏 | 真实模型或 GPU 成功 |
| 独立复跑 | 非作者真实 PG 80 项全部通过，包含原请求、锁序正/负对照、撤权、原任务 UNKNOWN 和提交后错误；修后 UI 18 项回归及 10 个独立反例通过 | 作者自审或真实模型研究成功 |
| 前端/静态 | 完整 npm check 548 项在前一 UI 候选通过；随后最终 UI 55 项定向回归及 tsc/lint/build 通过。生产/全部 npm audit 各 0；Ruff 通过，Pyright 0 errors / 14 既有 Windows 源码 warnings | 未检查的依赖或完整安全都已通过 |
| 浏览器 | 实际 PG、HTTPS/临时真实密码，桌面 1440×1000、手机 390×844 / 320px 无横溢。A 提问→B 浏览器离线回答→A 选择后下一轮采用；仅 3 次脚本 provider 请求；刷新/往返 0 新调用，双击 1 问题，撤权后新轮 409/0 调用 | 外部模型或生产 TLS兼容、全站易用性完成 |
| 网络中断恢复 | 浏览器阻断第一次 POST 到服务端；专用 404 查询和刷新均不发送，用户双击手动重发仍使用同 requestId/助手/文本，仅一个 B 原任务。退出清正文的边界经组件独立反例验证 | 自动重试或丢失原文后可猜测发送 |
| 真 OS 退出 | 两次实际退出/不同 PID 重启；消息/关联提交后尚无任务，只读和重复请求 0 派发，B 显式接续后 1 原任务/1 脚本调用；已有 RESERVED/task 无 runId 时始终原 task、0 调用。无 SQL 改任务状态 | 把 RESERVED 误称 UNKNOWN，或读取即恢复执行 |

## Findings retained

- 原回复采用路径与平台协议拒绝取消存在锁序反向。修为短 metadata 写事务统一 admission → session，模型/运行调用仍在事务外；独立反例及累计审查结论见 review.md。
- 消息已提交后，最终投影若因成员失效返回普通 403，前端可能误认为未发送。提交后 HTTP 异常现在标记原消息已保存、结果未确认；恢复权限后同原请求仍只有原任务与预算。
- 预算关闭的字符串异常经 HTTP handler 后原先丢失具体错误代码。提交前已知错误改用窄结构化响应，不改变全局异常处理器或增加泛化兜底。
- UI 原实例迟到响应可能清除新请求指针；提交前预算关闭也可能遗留不可恢复指针。修复与独立反例记录在 review.md。
- 网络失败且首次请求未到服务端时，原查询未找到原先会卡住发送。新增明确的同原 ID/助手/原文本手动重发；已有原记录只读，查询本身不执行。正文沿现有草稿的退出登录清理边界保存，退出后缺少原文只允许核对。

## Not verified

本片没有调用真实 Go、外部模型或个人 GPU/SSH；没有新增持续凭据或修改网络安全配置。此前会话/摘要片的真实 Go 证据不能冒充本片的实模闭环。未验证 64GB / 30 活跃会话容量、研究结论质量、完整 OS 隔离、生产可信 TLS 或用户环境部署。浏览器使用隔离数据库、真实临时密码和脚本 provider；临时自签 HTTPS 仅用于本地测试，不是用户服务。

GitHub 推送提示默认分支有 2 条 Dependabot 告警（critical / moderate）；现有集成读取告警详情返回 HTTP 403 `Resource not accessible by integration`，已停止该读取，未换渠道绕过。npm 两类审计为零，不能据此判断上述告警对象或影响，详情仍未核验。

## Browser artifacts and failures

[桌面采用回复](../../../docs/images/research-assistant-conversations/desktop-adopted-reply.png)、[手机字段错误](../../../docs/images/research-assistant-conversations/mobile-question-error.png)、[手机原请求恢复](../../../docs/images/research-assistant-conversations/mobile-original-request-not-found.png)、[撤权后的引用](../../../docs/images/research-assistant-conversations/mobile-revoked-copy.png) 均来自真实渲染，已逐张检查，无秘密；SYNTHETIC QA 为隔离测试数据标注。

最终浏览器和 OS 退出时 Git head 为 `b74ba67`，28 个产品文件与 `66f3915` 一致，源码前后不变；研究 bundle 为 `index-fDf655dV.js` / `index-hi-wzxHk.css`。最初两次浏览器失败来自 QA 的受控 textarea 精确 label 定位，第三次来自按钮出现早于网络回调完成的等待时序；保留原失败，修测试定位/等待后通过，没有为通过修改产品。原生 QA 前两次准备失败来自隔离夹具漏配工作目录/命令权限，也保留原记录，未当成实模失败或绕过权限。

## Next slice

在既有目标、共享权限、预算和停止边界内接 Agent 自主提问及异步证据返回，复用原消息、Registry、RunContext 和既有投递机制，不增加第二总线或逐条人工审批。迟到回复不擅自唤醒已停止研究，UNKNOWN 原任务不重放；其后继续全站易用性与可部署版本验收。
