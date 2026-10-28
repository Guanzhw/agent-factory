# Independent review

2026-10-28，非作者 `/root/compare_review` 审查；前端子审查由 `/root/compare_review/hook_early_review` 完成。

**结论：累计代码、交付文档与截图审查 PASS，无未关闭的审查阻断。** 精确基线 `3ec76ad34a97c3803933df646fd30966d4019024`，产品代码头 `20b9145fcc205213706b7dda26f908a4c50ca599`。完整覆盖累计 34 个文件，另核对本次 verification/tasks 与三张 PNG；先审 `50fce79f` 的完整累计改动，再逐项复审部署、手机反馈及读取时序增量。最终 PR head CI、合并与 main CI 由发布门槛独立核验，本文不预先宣称通过。

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
- 只读复核独立 QA 的真实 HTTP 停止、正常服务重建后显式继续、两个真实 OS 退出窗口及原生共享撤回。UNKNOWN / DONE-before-history 在 attempt 2 阻止 provider 和命令重放；共享撤回阻止后续请求。此组源码为 `50fce79f`，相关后端到最终产品头未变；模型为 scripted。

具体结果、版本映射与运行限制见 [verification.md](verification.md)。原始失败和整改证据保留，未用新成功覆盖旧失败。

## Simplicity and delivery boundaries

复用 Agno 3.1.0 原生 Agent loop、原 task/admission、effect、权限和进程 helper；没有新 harness、多后端框架、角色系统、跨租户 Team、demo 或假任务。应用仅增加逻辑会话与必要接点；R1/R2 是局部身份/观察修复，无通用恢复框架。未发现应阻断的过度防御、无谓 fallback 或冗余注释。

三张最终 `20b9145f` PNG 已逐张目视检查，并与 `browser-refresh-race-1793158864743519531` 的 QA 原图逐字核对：仅 SYNTHETIC QA/测试模型和账号，无真实个人内容、密码或凭据，无 PNG 附加 metadata，适合按现有仓库授权公开。截图是实际渲染，使用 scripted 终答测试状态，不是实模研究证据。Library 发现层 401 没有被写成上传成功，也未用其他路径绕过。

命令仍使用部署 OS 用户权限，不是 OS 沙箱。真实 GPU/SSH、30 活跃会话容量、长期摘要、完整隔离和研究质量未验证；充分恢复操作、跨助手整合及全站 UI 整改仍属后续。当前没有生产部署或用户可访问预览 URL。
