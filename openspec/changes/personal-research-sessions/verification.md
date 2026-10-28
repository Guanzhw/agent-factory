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

最终代码基线：`3ec76ad34a97c3803933df646fd30966d4019024`；产品代码头：`5c110376cb26b2c84b01cecf78de82d44ca7e802`。验证文档后续提交不改变这些源码。精确交付 head、CI 和合并结果以 [PR #151](https://github.com/Guanzhw/agent-factory/pull/151) 的提交与检查为准，不把待运行检查写成通过。

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

## Unverified at the first slice

真实个人 GPU/SSH、64GB/30 活跃会话容量、自动长期摘要、完整安全隔离和研究质量未验证。本地命令按显式配置的 OS 用户权限运行，不能声称跨租户命令隔离。没有生产部署或用户可访问预览 URL。

## Actual browser screenshots

产品源码 `20b9145fcc205213706b7dda26f908a4c50ca599`，实际 HTTPS / PG / 密码登录。图中 SYNTHETIC QA 仅为隔离测试数据；本组定向检查使用三个 scripted 终答验证界面状态，没有调用真实模型或研究工具，不替代前述真实 Go 证据。三个 PNG 均由作者之外 QA 与协调者逐张看过。

- [桌面会话完成与显式继续](../../../docs/images/research-sessions/desktop-completed-state.png)
- [320px 手机导航与完成状态](../../../docs/images/research-sessions/mobile-320-navigation-final.png)
- [手机展开并定位首个字段错误](../../../docs/images/research-sessions/mobile-collapsed-limit-error-visible.png)

最终截图校验 `qa/final-candidate-map.json`：构建产物及相关源码 SHA 与 20b9145 一致；运行前后无变化。完整浏览器流程在 50fce79 上验证，最后 UI 改动在 20b9145 定点复验。

`qa/browser-refresh-race-1793158864743519531/result.json` 真实 HTTP 延迟/故障验证：列表的新 running 状态不会被旧详情的 503 或晚到 200 覆盖，DOM 观察没有短暂回退。故障撤除后手动刷新恢复；正常完成由自动轮询同步另已验证。列表与详情仍是独立快照，故意延迟旧 200 时可短暂看到“列表执行中、详情旧可继续”；本片不宣称线性一致，后端单活动轮次权限不由这些文字决定。

## Full CI portability correction

[首次 full 40636456570](https://github.com/Guanzhw/agent-factory/actions/runs/40636456570) 对应 `e0f767225c163e82848daae7abd91f2420e9b892`。Windows Python 静态检查发现 8 个 POSIX `os` 标志类型错误，不能用已通过的 fast 或前端 job 代替本次失败。

修复产品头 `5c110376cb26b2c84b01cecf78de82d44ca7e802`：必需的 POSIX 标志使用无默认值的读取，缺失时仍报错；非 POSIX 目录访问在打开前拒绝。命令关闭时不再用 Windows 默认搜索路径的相对段阻断共享证据功能和默认装配；命令启用仍要求绝对路径，参数类型始终严格检查。没有 `getattr(..., 0)`、检查豁免、依赖升级或 Windows 本地命令支持声明。

17 项工具/装配回归通过，包括真实 Linux 临时文件、父子进程和 4 项可移植配置检查；普通与 Windows 目标的 Pyright 均 0 errors（Linux 环境中 14 条原有 win32 缺模块 warnings）。Windows 目标静态检查不冒充真实 Windows 执行，仍须新的精确 head full。UI 文件和截图未变，原实际浏览器版本继续按前文标注；本次不重复模型调用。非作者增量复审见 [review.md](review.md)，最终 CI 结果记录在 PR。

修正后的 `a28abd9` full [40638208697](https://github.com/Guanzhw/agent-factory/actions/runs/40638208697) 已实际通过 Windows Python：Pyright 0 errors / 0 warnings，发现 2314 项、跳过 911 项，4 项新增配置检查均实际执行。此结果只证明默认/共享证据装配兼容，不证明 Windows 宿主命令；其余门槛仍以最终交付 head 为准。

## PostgreSQL test interleaving correction

首次 full 的 PostgreSQL 终态另有 1 failure / 0 errors / 15 skips（发现 2310 项），`accepted=false`：`test_05_owner_key_manifest_catalog_and_budget_conflicts` 期望 `PREPARED`，实际为 `CANCELLED_NO_DISPATCH`。六组必跑检查均成功，不能抵消 discovery 失败。本次测试修正前，该测试及对应远程交接/生命周期源码与 main 基线一致。

作者和非作者分别在 `a28abd9` 固定快照、独立一次性 PostgreSQL 中复现两条路径：暂停后台观察器时，原测试的预算拒绝 403 后仍为 `PREPARED`；在预算为 4 的拒绝窗口显式调用真实 `observe_root` 与 `reconcile`，则确定性触发同一断言失败。观察器依法持久取消已不符合当前预算的任务，恢复预算后再次派发仍为 409；始终没有原生票据、run 或模型调用。这解释了本次失败，不将其泛称为偶发错误，也不归因于历史 MCP 超时。

只修正测试边界：原例暂停/恢复观察器以严格检查同步拒绝；新增独立例严格检查观察器取消、原绑定不变、预算恢复不复活及零派发。不放宽状态断言，不改产品、授权、CI 或 skip。作者的真实 PG 定向 8 项和非作者独立复跑的两条关键路径均通过（0 failure/error/skip）；测试文件 SHA256 `323f724d0b517e952782ec425222cbe33ca11afcb844531babd7b09dff2823e8`，原反例与独立复审见 [review.md](review.md)。最终测试修复提交仍需重新通过准确 head 的 full，不能复用 `a28abd9` 的门槛。

## Context continuation — PR #152

本片基线为 `3295b0addd235644ba44bdf3710085c60d44db26`，Agno 保持 **3.1.0**。下列证据与前文 PR #151 分开，未用旧片结果代替新功能验收。产品候选 `91c1224efbf838919126fed87e2a1f441d728650` 已完成分层验收；最终交付 head 的 full 和合并仍是独立门槛，不预先计为通过。

### PostgreSQL and protocol checks

作者在独占随机 PostgreSQL 中运行最终 34 项会话/摘要契约，0 failure/error/skip；包含原文和非已确认回复保护、started/ready/迟到响应、撤销与停止、原任务未知不绕过、边界容量及失败分类。此组原生票据/终态为显式 fixture，不是进程崩溃证据。首次 28 项中的一项因测试夹具误用 ContentPublication 字段报错，修正后通过，失败日志保留；未改产品字段迎合夹具。

独审在 `a505741` 发现真实边缘：整理期间接受四条 2000 字符纠正，合法 3000 字符摘要加包装后超过 12000，却误记结果未知。`91c1224` 计入实际包装并将已知本地容量拒绝记为 failed；原始文本不截断、不重打。最终准确边界投影 12000 可成功，额外纠正拒绝且不保存。原失败与修复日志均保留，独立复跑结论见 review.md。

### Real Go and local tools

独立 QA 在产品 `a50574170126bdd384c1924c80d433f86bd20db1` 上实际完成 **1 次原生摘要 + 3 次主研究/工具续接请求**，模型 `glm-5.3-flash`。全部 HTTP 200、返回 billing_source=go、额外 cost=0，没有 provider 回退；既有 Go 秘密只由测试出口在内存中注入，未复制进产品或持久配置。临时 PG、真实 native queue 和真实密码认证经 ASGI 客户端运行；浏览器/TLS另验，不声称产品直连 DNS 出口或部署已经验证。

前置 failed→completed 两轮由明确标记的 scripted provider 经真实 queue 产生，长研究叙述是合成数据。真实 Go 继续时，逐请求核验目标、停止边界、用户原文/ID、来源 ID、原 task/run/effect 状态；原失败仍为失败，原长回复仍保存。实际 research_read_file 读取临时 `check_value.py`，research_run 执行 `python3 -I check_value.py`，退出 0 并输出 `ACTUAL_LOCAL_CHECK_OK_735`；本例不修改文件、不验证研究质量或 GPU。

本例未发送运行中纠正。原 usage 里 correctionExact=false 表示没有此输入，QA 已另附 NOT RUN 说明，不能计为真实模型纠正通过；该行为由后续 scripted provider + 真实 PG/浏览器单独验。独立 reviewer 已核对原始请求/响应、工具事件及版本；后续容量修复以定向 PG 反例验证，不把 a505 的实模记录改标为 91c1224 实跑。

详细产物保存在云端 `/workspace/design-audit/research-context-20261028/`：`backend-contracts-p2-capacity-fix.*`、`independent-capacity-counterexample/`、`qa/live-context-1793185092142197072/`。这些本地路径不是公开下载链接；仓库中的产品回归与本记录提供可检查的事实边界，精选实际截图见下文。

### Real process exits and browser

产品 `91c1224` 的两个真实 OS 退出窗口全部通过：started 时 PID 129300 退出 86，新 PID 129466 恢复同 task/run 的 native attempt 2，摘要总计 1 次、主请求 0 次，结果保持 unknown；ready 保存后 PID 130006 退出 87，新 PID 130182 恢复同 task/run、复用同 checkpoint，摘要总计 1 次、主请求 1 次。没有手改任务终态；两者 GET、原请求查询与重复原提交均新增 0 次调用。后者是既有队列恢复原已授权轮次，不是读取页面触发或新建轮次。全部 provider 为 scripted，真实 PG/OS 行为不冒称真实模型中断。

实际浏览器使用临时 PG、真实密码登录和 loopback HTTPS，浏览器仅对该临时自签证书忽略信任错误，不证明生产可信 TLS。desktop 1440×1000、mobile 390×844 以及 320px 无横向溢出，pageErrors 为空。摘要期间在手机提交纠正，先保持 pending，仅主研究请求才变 included；桌面双击只产生 1 轮；刷新与浏览历史新增 provider 调用为 0。本组总计 1 次摘要/1 次主请求，全部 scripted。前两次 QA 的 Playwright 路由事件阻塞、临时 PG TCP 就绪时序失败保留，修的是验收脚本，不是产品或认证。

本组 build `index-7qsWlz2Z.js` SHA256 `3d1a0f2d8490957add3e494d9803d89e3287fee0326e621d153cb59e08aa45ea`；产品/构建 SHA 与运行前后快照匹配。三张原始 PNG 经 QA 和协调者逐张查看，SYNTHETIC QA 是测试浏览器添加的标识，不是产品 demo 模式：

- [桌面：正在整理，指令待纳入](../../../docs/images/research-session-context/desktop-preparing.png)
- [桌面：纠正纳入与摘要覆盖范围](../../../docs/images/research-session-context/desktop-ready.png)
- [手机：摘要范围及下一轮输入](../../../docs/images/research-session-context/mobile-ready.png)

可复核原产物为 `qa/restart-context-1793185822348672387/`、`qa/browser-context-1793185879378720236/` 与 `qa/REPORT.md`。本轮测试进程与自有临时 PG 均已清理；未部署给用户，没有公共预览 URL。真实 GPU/SSH、目标硬件容量、研究质量及完整 OS 隔离仍未验证。
