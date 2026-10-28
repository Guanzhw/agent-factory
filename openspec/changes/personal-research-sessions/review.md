# Independent review

2026-10-28，非作者 `/root/compare_review` 审查；前端子审查由 `/root/compare_review/hook_early_review` 完成。

**初始累计审查：代码、交付文档与截图审查 PASS，无未关闭的审查阻断（20b 产品头；后续 5c Windows 增量见末节）。** 精确基线 `3ec76ad34a97c3803933df646fd30966d4019024`，产品代码头 `20b9145fcc205213706b7dda26f908a4c50ca599`。完整覆盖累计 34 个文件，另核对本次 verification/tasks 与三张 PNG；先审 `50fce79f` 的完整累计改动，再逐项复审部署、手机反馈及读取时序增量。最终 PR head CI、合并与 main CI 由发布门槛独立核验，本文不预先宣称通过。

## Findings closed

- **R1：迟到取消误停新轮。** 独立反例复现旧 stop 按最新轮次选目标、旧 task 回调停止整个会话。现 stop 回执固定原 turn/request；旧回调不影响新轮，已停止的旧 reservation 也不能在新轮开始后恢复派发。真实 PG 延迟交错与重复请求配对通过。
- **R2：旧观察永久覆盖完成结果。** 独立反例复现 running 观察与后读 terminal 位混用，导致后续永远跳过最终回复。现只持久化一致终态，完成正文核对原 run；新轮等待已核实结果。并发旧读和迟到 admission ACK 错误不再覆盖确认结果；failed/canceled 可继续但不伪造答复。真实 PG 配对通过。
- **UI P2：旧详情覆盖新列表。** 两个独立反例分别覆盖详情刷新 503、旧详情晚成功。局部读取代际修复后，22 项相关产品测试与原两个反例在 `20b9145f` 固定快照全部通过；不依赖时间戳排序，不增加全局状态层。列表与详情仍是分别读取的快照，可短暂不同，不宣称线性一致性；后端原任务守卫继续拒绝无效重复启动。
- 保持此前修复：同步/异步模型钩子后的停止检查、完整 admission 载荷 fingerprint、结构材料复用、共享来源与撤销、纠正跨轮持久状态、idle 继续入口和 StrictMode 草稿。
- 最终增量解决手机首错误屏外不可见、折叠限制未展开、完成状态与列表不同步，以及 HTTPS `--factory` 启动未读取显式工具配置。无参 factory 与 CLI 共用一个配置 helper；显式 Settings 不继承环境工具授权。

## Verification reviewed

- Reviewer 独立执行真实随机 PostgreSQL 完整 16 项会话契约测试，最终后端两文件 SHA 前后相同；包含 R1/R2、迟到 ACK、载荷篡改、纠正、共享撤销与上下文边界。native 身份和观察边界部分为显式 fixture，不能当服务崩溃或真实模型验收。
- 独立执行模型协议/钩子/端点 36 项及最终 HTTPS composition 3 项；工具早期独立临时文件/父子进程检查通过。外部回复 `tool_calls:null` 兼容未放宽真实工具调用、参数或私有 continuation 校验。
- 前端固定提交快照审查及针对性测试通过，最终源码 24 项独立检查包括原两项失败反例。真实浏览器由作者之外 QA 执行；已复核最终 `20b9145f` 的手机错误实际坐标、503/晚 200 配对、源码/构建映射与三张新截图。故障配对恢复经过手动刷新；正常完成自动轮询另有验证，不混同两者。未把 happy-dom 或错误 DOM 存在当视觉验收，也未用旧图冒称最终构建已验证。
- 只读复核真实 Go 两轮脚本、工具事件与 14 条回执：同逻辑会话、不同任务，两次真实测试失败→修改→成功。Reviewer 未追加模型调用。此链在 `abf277f0` 执行，后续状态修复以 PG/进程验证，未假称实模重跑最终头。
- 只读复核独立 QA 的真实 HTTP 停止、正常服务重建后显式继续、两个真实 OS 退出窗口及原生共享撤回。UNKNOWN / DONE-before-history 在 attempt 2 阻止 provider 和命令重放；共享撤回阻止后续请求。此组源码为 `50fce79f`，相关后端到 `20b9145f` 时未变，后续仅工具跨平台修正见末节；模型为 scripted。

具体结果、版本映射与运行限制见 [verification.md](verification.md)。原始失败和整改证据保留，未用新成功覆盖旧失败。

## Simplicity and delivery boundaries

复用 Agno 3.1.0 原生 Agent loop、原 task/admission、effect、权限和进程 helper；没有新 harness、多后端框架、角色系统、跨租户 Team、demo 或假任务。应用仅增加逻辑会话与必要接点；R1/R2 是局部身份/观察修复，无通用恢复框架。未发现应阻断的过度防御、无谓 fallback 或冗余注释。

三张最终 `20b9145f` PNG 已逐张目视检查，并与 `browser-refresh-race-1793158864743519531` 的 QA 原图逐字核对：仅 SYNTHETIC QA/测试模型和账号，无真实个人内容、密码或凭据，无 PNG 附加 metadata，适合按现有仓库授权公开。截图是实际渲染，使用 scripted 终答测试状态，不是实模研究证据。Library 发现层 401 没有被写成上传成功，也未用其他路径绕过。

命令仍使用部署 OS 用户权限，不是 OS 沙箱。真实 GPU/SSH、30 活跃会话容量、长期摘要、完整隔离和研究质量未验证；充分恢复操作、跨助手整合及全站 UI 整改仍属后续。当前没有生产部署或用户可访问预览 URL。

## Windows full CI 修复增量复审

首次 full [40636456570](https://github.com/Guanzhw/agent-factory/actions/runs/40636456570) 的实际 head 为 `e0f767225c163e82848daae7abd91f2420e9b892`，事件 `workflow_dispatch`、attempt 1、scope `full`，并展开 Ubuntu/Windows。独立读取 Windows Python job 日志确认 `session_tools.py` 有 8 个 POSIX `os` 标志类型错误；Ubuntu Python 被 fail-fast 取消。这次 full 不能计为通过，不用此前 fast 结果替代。

已独立审查修复 `e0f7672` → `5c110376cb26b2c84b01cecf78de82d44ca7e802` 的完整两文件增量，**代码复审 PASS**。POSIX 标志改为无默认值的动态读取；缺少必需标志会在打开文件前失败，没有 0 fallback、类型忽略或放宽 `dir_fd` / `O_NOFOLLOW` / `O_NONBLOCK`。非 POSIX 显式 workspace 仍拒绝。仅启用 host commands 时要求搜索路径各段绝对，解决 Windows 默认 `os.defpath` 含相对段导致禁用配置也不能装配的问题；布尔值和路径类型检查保持。默认工具仍只提供共享证据读取，未新增 Windows 宿主执行能力、CI skip 或配置例外。

Reviewer 在精确修复字节上独立执行 17 项工具与 HTTPS composition 检查全部通过，包括实际 Linux 临时文件/符号链接拒绝、原生 Agent scripted 两轮读改测试、父子进程停止及 4 项新增配置反例。仓库原配置 `pyright --pythonplatform Windows` 为 0 errors / 14 项本机既有 Win32 缺失源警告，Ruff 与 diff check 通过；这不是原生 Windows 执行证据。产品文件 SHA `71013afbf12f13893ea0725b2b859e38eef0bcba2f31be06ac1326469d2671b7`，对应测试 SHA `b04730fcca113b30d380175724f413ac0fcd08584d01d26ee108220b1d089693`。其余已审产品字节未变，累计审查结论保持；新最终 head 的真实 Windows/full CI 门槛仍须另行核实。

## PostgreSQL 观察器测试增量复审

累计基线仍为 `3ec76ad34a97c3803933df646fd30966d4019024`，本次增量基线 `a28abd9d9e85b25e0c2db35f8164267a152fff9d`。独立读取首次 full 的完整 PostgreSQL 日志，确认 2310 项、1 failure / 0 errors / 15 skips、`accepted=false`；六个必跑组全部通过不能抵消 discovery 失败。失败为原预算冲突测试预期 `PREPARED`、实得 `CANCELLED_NO_DISPATCH`。第二轮 [40638208697](https://github.com/Guanzhw/agent-factory/actions/runs/40638208697) 的 Windows Python 已实际成功，新增 4 项配置检查实际通过；完整 PostgreSQL 在本复审时仍运行，未预先计为成功。

Reviewer 在原 `a28abd9` 独立 Git 归档及一次性真实 PostgreSQL 上复现：原测试暂停观察器后通过；在真实 403 返回边界、预算仍为 4 时显式运行原生 `observe_root`/`reconcile`，原断言确定性失败。没有伪造权限结果或写入取消状态；实际产生 `protected_denied`、`current-authority-ended` 事件，原任务从未派发，恢复预算后仍拒绝 409。这证明原测试混入了合法的观察器清理交错，不能把该失败笼统归为环境偶发或历史 MCP 问题。

**测试增量审查 PASS。** 完整审查唯一测试文件的 48 行新增 / 5 行删除：原例只在预算拒绝窗口停止/恢复观察器，保留精确 403、`PREPARED` 和无新票据断言；新独立例验证实际观察器取消、原绑定不变、恢复预算不复活和双方零派发。没有放宽状态集合、修改产品或新增 skip/CI 例外，未引入多余测试框架。冻结测试 SHA256 `323f724d0b517e952782ec425222cbe33ca11afcb844531babd7b09dff2823e8` 在独立归档中真实 PG 复跑两项全部通过（5.529 秒，0 failure/error/skip）；原反例和修复验证各使用新临时容器并已清理，未调用模型。Ruff 与 diff check 通过。产品头仍为 `5c110376`、UI 仍为 `20b9145f`；新的测试/文档交付头需单独通过完整 CI，不能复用前两轮结果替代。

## Context continuation 方案审查

2026-10-28，非作者 `/root/compare_review` 完整审查本次 proposal/design/tasks/spec，辅助模型调用链由 `/root/compare_review/hook_early_review` 交叉复核。**方案 PASS，无未关闭的方案阻断；仅允许进入实现，不代表新增功能已通过验收。** 本片基线为已合入的 `3295b0addd235644ba44bdf3710085c60d44db26`，与上文首片审查分开。

原生 Agno 3.1.0 SummaryManager 无 RunOutput、OwnerChatModel 拒绝 response_format、旧 task 终态不能借身份、既有 before_model 持事务及 12k 准入先于运行等实际接口均已核对。方案采用当前活动 turn 的窄辅助绑定和精确 JSON-object 文本桥、事务外摘要、可信历史 prefix 与有界保护包，解决这些接点而不改全局 task/session 不变量或通用 codec。目标、全部用户原文、来源与操作事实独立保留；仅压缩回复叙述，不引入新 harness、队列、记忆系统或账本。12k/3k/48k 为字符界限，不是 token/费用保证。

摘要 started/unknown 在同 task 不重打；原 task 真正安全终态且无业务 UNKNOWN/custody 后才允许用户显式新 turn 重试，失败也计入原 maxTurns，旧回执不能覆盖新 checkpoint。该区别合理，不为只读摘要增加永久死路，也未放松原工具副作用防重放。摘要阶段不得标记主请求已纳入纠正；来源撤销/停止须在保存及主请求前重新核查。

实现验收仍须实际覆盖：旧超限会话准入与保护区超限拒绝、原生摘要→主请求同 owner/model 且零工具/无递归、摘要挂起时纠正和停止可提交、撤权后零主调用、started/ready 两个崩溃窗口、重复请求与旧回执迟到、无效/超长摘要保留原历史；最终上下文的序列化大小也须满足界限。PG/scripted、真实 Go 小例和桌面手机分别给证据，不以首片成功或本方案审查替代。

本轮独立 `openspec validate personal-research-sessions --strict` 通过；没有新增模型、PG或产品测试调用，没有产品修改。审阅文件 SHA256：proposal `cb608be95048d6eec9dbe4681289ea7f884cad47f3b2e99cfade04538678a277`；design `4c5cb42b70fb9ff8fa196c978d56eeb5f03dc0852936dab51e1a9cbf599c3fb4`；spec `72837bf62d49cc134c486c4921ad2401d391e4995ba017f4bc7e91ab43b265d2`；tasks（4.1 勾选前）`89c3ef3f426fd437ceb13a7e0f670eee26228d32bbbb9efecf19047ad40590e7`。

## Context continuation 实现审查

**累计实现与验收证据审查 PASS：容量/失败分类反例已整改并独立复验，实际浏览器与两个 OS 退出窗口证据已核对，无未关闭的代码或验收证据阻断。可冻结最终交付 head 并进入准确 head 的 full CI；尚未将 CI、合并或部署计为通过。** 本片累计基线 `3295b0addd235644ba44bdf3710085c60d44db26`，先完整审查候选 `a50574170126bdd384c1924c80d433f86bd20db1` 的 16 文件，再完整复审产品头 `91c1224efbf838919126fed87e2a1f441d728650` 的三文件增量。UI 四文件完整审查与 23 项产品回归、6 项独立交错反例通过；core 11 项独立协议检查、原生摘要至 OwnerChatModel 两协议的 8 项离线检查通过，相关 SHA 与最终产品头一致。真实随机 PostgreSQL 上初次独立复跑 32 项会话/摘要契约全部通过（41.861 秒、0 failure/error/skip），原生任务/queue 观察在该组仍为显式 fixture，不能替代 OS 退出和真实模型验收。

新增独立真实 PG 反例曾在 `a505741` 复现：摘要进行期间接受 4 条各 2000 字符的纠正，保护区 8977 字符；模型返回合法、恰为 3000 字符的摘要对象，最终投影加包装字段超过 12000。代码确实拒绝主研究请求、保留原历史和 pending 纠正，但把已知 `RESEARCH_CONTEXT_LIMIT` 归为 `unknown/RESEARCH_SUMMARY_UNKNOWN`，错误表示模型结果未确认。独立反例 SHA256 `398a41d1016b86c3724b417e58cdec4bb5aa26e0bb49a4e82aaeb02e395d1951`，观察结果 `c6f43e0cbe1804efc15bb15fae944411f366ed0045657d9d3623d2badfe446f5`；初次自写 fixture 的整点容量假设失败单独保留，不当作产品失败。

`91c1224` 用一个局部 helper 计算实际摘要包装容量，在准入和运行中纠正共用；已收到结果后的确定容量拒绝单独记 failed，来源撤销、网络或落盘不明未被宽化为已知失败。没有放宽上限、截断原文或自动重试。Reviewer 在最终三文件 SHA 稳定的真实 PG 环境独立运行 **34 项产品契约 + 2 项独立边界反例，36 项全部通过**（51.225 秒、0 failure/error/skip）。独立例直接构造实际序列化投影、不调用新容量 helper 计算期望：12000 字符投影和 3000 字符摘要可 ready，额外纠正拒绝且未写；摘要期间原 `_refresh` 补齐 task/run 身份后触发已知容量失败，状态/原因准确、全消息 pending、无 checkpoint，attempt 2 不重打。脚本 SHA256 `452b72ef0f5c80a7d85d8a6bbc59b8e980cb6bb46ec708d1a50fa8b083bcd7c1`，结果 JSON `eaebab04e3ff73eb94c6506665aa9829625e063b478a8fafb767d4a4f71fb083`。

同时复核两项前置修复：未参加摘要的 failed/canceled 回复仍保留；`_refresh` 在写锁内重新判断 compaction，锁外 started 观察不再把已 ready/completed 的结果改成失败。方案与使用文档的 12k/3k/48k、显式摘要触发及下一片交接边界一致；无新 harness、通用状态层、权限系统、无谓 fallback 或测试 skip。基线 UI 的迟到 A 请求会显示无会话名的全局 notice，但不会覆盖 B 的摘要/草稿；本片未声称所有提示已隔离。

真实 Go 小例已只读复核脚本、4 条原始响应/用量和工具事件：在 `a505741` 完成 1 次原生摘要、3 次主请求，真实读取与本地测试退出 0；前置历史是明确 scripted、运行中纠正该例 NOT RUN，不能宣称研究质量或完整实模历史验证。后续容量修复由上述 PG 边界验证，不改标旧实模版本。Reviewer 未追加外部模型调用、修改产品或安装依赖；上述临时 PG 容器均已清理。


最终只读复核独立 QA 的 `91c1224` 原始结果、脚本、请求计数及源码/构建映射：真实 OS started 退出后原 native attempt 1→2，摘要总 1、主请求 0，保持 unknown；ready 事务提交后退出，同 task/run 的原队列 attempt 2 复用同 checkpoint，摘要总 1、主请求 1。没有手改 task/effect 状态，GET、原请求查询和重复原提交均新增 0 次调用。该 ready 路径是恢复已授权的原任务；不是页面读取创建任务，也不代表安全终态会话无需显式开始下一轮。两者 provider 为 scripted，不把受控断点当远端模型 exactly-once 保证。

浏览器真实使用临时 PG、密码登录、loopback HTTPS 与 Chromium；已核摘要期间纠正 pending→仅主请求 included、双击仅 1 轮、刷新/历史零新增调用和手机空输入反馈。1440×1000、390×844 及 320px 无横向溢出；临时自签证书的测试信任例外不是生产 TLS 验收。Reviewer 已逐张查看三张交付 PNG 及手机错误截图；三张仓库文件与最终 QA 原图逐字相同，仅 PNG 图像块，无附加 metadata，内容为明确 SYNTHETIC QA/临时账号与合成输入，无真实个人材料或秘密，适合在现有仓库范围公开。未把这些 scripted 截图当实模研究结果。

最终累计核对 **20 个文件**（含文档及三张 PNG）：使用说明的 ready 自动续原任务与 started 不重打边界准确；verification 保留真实 Go `a505741` 与最终 `91c1224` 的不同证据版本、两次 QA 夹具失败和未验证范围；tasks 4.7 保持未完成，下一片只作已核源码的任务交接。未扩大本片实现或提前声称生产部署。最终交付提交产生后，只需核其字节与本审阅快照一致，并独立核验准确 head 的 CI。
