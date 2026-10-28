# Verification

交付 PR [#151](https://github.com/Guanzhw/agent-factory/pull/151)，基线 `3ec76ad34a97c3803933df646fd30966d4019024`。依赖仍为 Agno 3.1.0；3.1.10 spike 不作为本片产品验收。

## Evidence boundaries

| 验证层 | 实际证据 | 不代表 |
| --- | --- | --- |
| 原生工具 / 临时文件进程 | 真实文件读改、测试 exit 1→0、父子进程组取消；native Function/Agent 使用 scripted model | 真实模型研究质量、OS 沙箱、逃逸进程或远端停止 |
| PostgreSQL / 原生队列 | 独立随机测试库、身份/并发原请求/纠正/共享撤销；两种真实 OS 硬退出窗口：UNKNOWN 与 DONE-before-history 都在原生 attempt 2 阻止重放；另有正常服务生命周期替换后的显式继续 | 自动恢复未知实验；服务状态已知不等于远端 GPU 状态已知 |
| 真实 Go 模型 | 同一会话两轮、不同 task；两次真实 unittest 失败→修改→成功；中途纠正在下一模型请求纳入；修后 14 次请求均 HTTP 200、Go 订阅、cost=0 | 产品直接 DNS 出网验证。验收使用测试专用 egress transport，在内存注入现有 key；临时 vault 只存明确假占位值 |
| 浏览器 | 实际 HTTPS、临时真实密码、桌面 1440×1000 与手机 390×844；模型部分为 scripted。缺资源→配置返回、双击、刷新/前进后退、丢响应只读核对、跨用户拒绝，手机首错误自动聚焦并滚动可见 | 生产账户、公司身份提供者、真实研究数据 |

Go 首两次整链各 6 个已确认响应：终答 `tool_calls:null` 被原项目 codec 拒绝，任务失败；失败没有删成成功记录。两次单请求诊断后找到完整响应反例，最小修复外部可空字段，55 项协议检查及原 6 响应离线重放通过，再作 14 请求真实两轮复验。合计 28 次请求，全部确认 Go/cost=0，无付费回退。此问题不归因于 Agno 版本。

## Exact behavior

- 纠正先持久保存，在**下一次模型请求**加入；不是实时打断在途模型或命令。本轮直接结束则留给下一次显式继续。
- 已确认结束后，重开原会话或重启服务不自动执行。用户明确继续会创建下一任务，保留个人助手/会话和目标边界。
- 未知效果或历史尚未确认的重试保持原操作待核对，禁止新任务绕开；本片不提供自动接续未知实验或 GPU 重新提交。
- 保留原研究项目、工作流、QA 与独立应用往返；自动摘要、跨助手消息整合和全站易用性整改另列后续。

## Independent review

非作者 `/root/compare_review` 审查完整累计 diff 与简洁性。方案初审 B1–B3 已整改复审。代码审查推动修复同步停止检查、共享来源字段、下一轮入口、纠正状态、材料重复生成、StrictMode 草稿及手机导航。最终审查发现旧停止与终态刷新两个竞态，修复在 `50fce79f76e4752aad2662bc712cbb41f145c052` 经完整累计复审 PASS（33 文件）和独立 16 项 PG 回归。之后的 `e92393bdc944f68f173e66192a9f1d3de7d127b3` 修复手机错误定位、状态反馈及 HTTPS factory 工具环境接线；其后独立反例又发现旧详情（失败或成功晚到）覆盖新列表；`20b9145fcc205213706b7dda26f908a4c50ca599` 用界面局部读取代际修复双向返回顺序，22 产品检查加 2 独立反例通过。完整非作者结论见 [review.md](review.md)。未据旧 CI 或实模成功提前合并。

最终代码基线：`3ec76ad34a97c3803933df646fd30966d4019024`；产品代码头：`20b9145fcc205213706b7dda26f908a4c50ca599`。验证文档后续提交不改变这些源码。精确交付 head、CI 和合并结果以 [PR #151](https://github.com/Guanzhw/agent-factory/pull/151) 的提交与检查为准，不把待运行检查写成通过。

## Reproducible checks and evidence index

- `npm run check`：最终产品代码 55 文件 / 521 tests、lint、类型检查、构建通过。官方 npm registry 两项 audit：0 漏洞。
- `ruff check platform deployment applications scripts` 通过；`pyright`：0 errors，14 条原有 Windows 模块 warning。
- 新增 HTTPS factory 3 项无数据库检查通过；原 codec 55 项及 6 份实际响应离线重放通过。没有修改依赖锁。
- 独立代码审查 `pr151-code-final-review.md`，base 3ec→50fce，SHA256 `29acd5cd67e4f998ab8f236637663dcf362e893bb2abc1f80aa8cee3113a48ca`。R1 迟到取消不能影响后续轮次；R2 一致终态与迟到 ACK 不覆盖结果；均已修复。
- `live-corrected/live-result.json`、两 checkpoint 和账本：真实 Go 两轮，代码 abf277f；后续停止/刷新修复另以真实 PG / 进程验证，不声称真实 Go 重跑最终提交。
- `qa/backend-cases/native-stop-1793156966472136781/result.json`：50fce 源码，真实 HTTP 停止；父进程消失，子进程处于不执行的 Z 状态，不能说已回收。停止确认约 0.91 秒。正常关闭并重建服务后 GET 无执行，显式继续新任务、同会话、原命令仍只执行一次。
- `qa/backend-cases/restart-1793157320999692061/report.json`：50fce 源码，两次实际不同 OS 进程，原生 attempt 2 保留 UNKNOWN / DONE 原回执，provider/命令计数仍各 1；新轮次 409，未盲重放。
- `qa/backend-cases/native-shared-1793157589633663860/result.json`：Bob 真实发布→Alice 原生工具读→模型收到正文/来源；撤回后下一 provider 被阻止，新轮次 409 / 读取 404。私有未共享正文未进入 provider。模型 scripted，测试仅在真实工具返回后暂停以确定撤回窗口。

上述详细运行产物由云端任务保存于 `/workspace/design-audit/personal-research-20261028`，它不是用户公开下载链接。仓库保留可复跑的测试与这份事实摘要；精选截图见下方仓库实际 PNG。真实命令、队列和共享权限测试没有使用付费模型。

门槛：最终源码及文档独立复审、真实 HTTP 停止/重启正反例、桌面手机截图、精确 head CI；通过后才合并。

## Unverified

真实个人 GPU/SSH、64GB/30 活跃会话容量、自动长期摘要、完整安全隔离和研究质量未验证。本地命令按显式配置的 OS 用户权限运行，不能声称跨租户命令隔离。没有生产部署或用户可访问预览 URL。

## Actual browser screenshots

产品源码 `20b9145fcc205213706b7dda26f908a4c50ca599`，实际 HTTPS / PG / 密码登录。图中 SYNTHETIC QA 仅为隔离测试数据；本组定向检查使用三个 scripted 终答验证界面状态，没有调用真实模型或研究工具，不替代前述真实 Go 证据。三个 PNG 均由作者之外 QA 与协调者逐张看过。

- [桌面会话完成与显式继续](../../../docs/images/research-sessions/desktop-completed-state.png)
- [320px 手机导航与完成状态](../../../docs/images/research-sessions/mobile-320-navigation-final.png)
- [手机展开并定位首个字段错误](../../../docs/images/research-sessions/mobile-collapsed-limit-error-visible.png)

最终截图校验 `qa/final-candidate-map.json`：构建产物及相关源码 SHA 与 20b9145 一致；运行前后无变化。完整浏览器流程在 50fce79 上验证，最后 UI 改动在 20b9145 定点复验。

`qa/browser-refresh-race-1793158864743519531/result.json` 真实 HTTP 延迟/故障验证：列表的新 running 状态不会被旧详情的 503 或晚到 200 覆盖，DOM 观察没有短暂回退。故障撤除后手动刷新恢复；正常完成由自动轮询同步另已验证。列表与详情仍是独立快照，故意延迟旧 200 时可短暂看到“列表执行中、详情旧可继续”；本片不宣称线性一致，后端单活动轮次权限不由这些文字决定。
