# Personal memory verification

2026-10-28。记忆冻结 head 的完整 CI 已通过；子助手的分层验证如下。适用发布门禁仍暂停，不代表已合入 main 或已部署。Agno 固定 **3.1.0**。

## Revision and scope

- 实现基线：`04cef0d5e8f6737fa85ae8b53013306d5fabc134`；实际 Go 最终候选：`e023453bb510ecf9d029107ce20c26a47e344dd5`。
- 独立非作者完整审查覆盖上述累计 15 文件及简洁性，无未解决代码阻塞；22 个查询/身份/恢复/工具反例独立复跑通过。
- 本片只给现有研究会话加入本人偏好的查找、保存、纠正、忘记及结果展示，复用 Agno UserMemory/PG、现有执行身份和原操作记录。没有辅助记忆模型、向量库、demo 账户或新的管理系统。
- 记忆冻结候选不含临时 subagent；子助手另在依赖分支整合，见本文末尾。长期助手间异步问答不等于临时子助手或通用动态 teams。

## Actual evidence

| 验证层 | 实际结果与边界 |
| --- | --- |
| Python 回归 | `900e59f` 实现的 101 项通过，无跳过：14 PG 记忆、11 SQLite 记忆、76 个现有会话/上下文/回复/工具/装配用例。`e023453` 只澄清工具查询说明，11 个 SQLite 测试重跑通过；最终 full 仍须准确 head 执行。 |
| 静态与前端 | 全项目 Ruff 通过；Pyright 0 错误、14 个既有 Windows 库来源警告。`npm run check` 的 581 测试、lint、类型检查和构建通过；生产/全依赖 audit 均 0 漏洞。Research 独立构建也通过，未把 core 构建当成 Research 浏览器证据。 |
| 原生 PG/进程 | `900e59f` 的 5 组测试均通过，25 次明确脚本模型请求、0 次真实模型：跨用户已知 ID、停止、DB 异常、提交后回执前退出、后改值不重放、DONE 回执后最终回复前退出。实际 `os._exit(73)`，新服务 PID 读取同 PG；不是手工改 native 状态。 |
| 恢复语义 | 两个退出正例均保留原 task/run，native attempt 1→2 后原轮 ERROR，模型 3→3、写入不重放；核回原记忆后由用户显式下一轮 find，模型才 3→5。原轮没有被改成成功。后改值反例保留 UNKNOWN，不能开始新轮，也未覆盖新值。 |
| 真实 Go | `e023453`：**24 次实际 DeepSeek v4.1 Flash 请求、3 个独立会话、5 条用户指令**，全部 HTTP 200，账单来源 Go、cost 0、无收费回退。A 保存两偏好；真实服务/worker 退出再启动，读取不调用模型；B 找回两偏好，按记住的 unittest 命令复现 3 测试中的 2 失败、只修 `stats.py`，原 3 测试不改，实际和独立复跑均通过；最终回答采用格式偏好并包含于持久化回复。 |
| 真实 UI | 同一真实 Go 旅程用桌面自然语言纠正原记忆 ID、390px 手机自然语言忘记，C 新会话查询确认已忘记；双击仅 1 POST/1 轮。真实密码认证、真实 HTTP API，1440/390/320px 无横溢或 pageerror；刷新/前进/后退 0 写请求。空指令是客户端就地反馈，跨用户拒绝是服务端证据，两者分列。 |

真实 Go 使用测试专用进程入口、正常 Settings/API/原生 PG/worker和真实密码认证；Go 密钥只在进程内存中通过既有代理转发，不进入产物或持久凭据。没有改写模型请求内容/工具结果，不声称这是原封不动产品 CLI 的网络接入验收。

## Preserved failures and corrections

- 首次脚本 stop 复用了创建会话 requestId，正常服务返回 409。仅修正测试请求 ID，保留原失败；没有放宽幂等规则。
- 首次真实 Go 共 25 个请求后失败。第一处实际断言是未找回答案格式偏好：模型把空格分隔的多关键词用于原生连续文本查询，连续空结果被误认为没有偏好。最小产品修复澄清查询语义及无 query 列举方式，不新增检索框架、不把样例文本改成迎合关键词。
- 同轮测试夹具还假定已安装 pytest，实际解释器没有该包。改用已有标准库 unittest，保留相同 3 组测试输入及必须执行测试的断言；没有安装依赖或向模型提供参考修复。
- Go 补充代码审查的一次请求耗尽输出、没有最终意见，标为 INCOMPLETE；未用于替代独立完整代码审查。

## Screenshots

下面是最终候选的真实渲染，使用明确的临时合成账号/偏好；不是产品内置样例或生产数据。

- [桌面：原条目修改前后](../../../docs/images/research-personal-memory/desktop-corrected-memory.png)
- [手机：忘记结果与历史保留说明](../../../docs/images/research-personal-memory/mobile-forgotten-memory.png)
- [手机：空指令就地反馈](../../../docs/images/research-personal-memory/mobile-empty-instruction.png)

## Reproduction and remaining gates

现有隔离回归可用 `PYTHONPATH=platform:deployment:applications:platform/tests:applications/tests python -m unittest test_research_session_memory test_research_session_memory_postgres -v`；PG 需按 DEVELOPMENT_CHECKS 提供一次性 loopback 数据库。真实模型/OS 退出/浏览器脚本及原始失败保留在云端 `/workspace/design-audit/personal-memory-20261028/qa/`，运行必须使用明确测试配置和已有授权，不向产品添加测试模式。

原生汇总 SHA256 `64dd79f822dd0c8b5509dff4a93afa5d0852a40bebe3a6658b838f424f8af35f`；实模结果 `3d8240e35ba76151b203a0eb0fc32d420f23bf8d67b8808a9d952650ff38997d`；独审 `9177e26a50092225ff8d1a198d4f88024cc8b8094a2e23875a778d6281702b94`。

记忆最终 `0a7dca2352c21c278b084903293fc30b65568b01` 的 [full40772234713](https://github.com/Guanzhw/agent-factory/actions/runs/40772234713) 七 jobs 全成功，含 PG full/accepted 门禁、Windows full；独立 API 核对通过。日志/产物下载此前被拒，没有重试，故不编造原始用例数。适用发布/main 门禁尚待完成。

## Subagent integration acceptance

记忆产品基线 `e023453bb510ecf9d029107ce20c26a47e344dd5` → 子助手冻结 `40985ab837a0c01b35f490482f2c55e9e5b9c1e0`。非作者完整累计 20 文件审查与简洁性通过；固定 Agno 原生 delegation/external execution/原 ControlCommand，无新增调度器。以下是分层证据，不代表任意任务都能完成。

| 验证层 | 结果与边界 |
| --- | --- |
| PG 探针 | `124e53ee` 的 5 项真实 PG 验证：两个 worker、两成员各一 parent+child，原暂停/续入、同库服务重建、停止及未知结果守卫。整合另验证 parent/child 同 call ID 记忆归属；独立审查复跑关键反例。 |
| 实际进程退出 | `235eec` 原 child 结果已持久后服务 PID 退出，新 PID 续原 parent/run，attempt1→2、child不重建；UNKNOWN 用实际 `os._exit(73)`，40985复跑保持原命令计数1、脚本模型调用4不增。正常退出与崩溃分开记录。 |
| 实际停止 | 40985手机点击一次停止后0.847秒内命令父进程消失、后代为非运行僵尸，原父/子票据 cancelled，effect CANCELLED/stopped=true；清理未发送 kill，不能用清理替代产品停止。 |
| 真实 Go 只读分工 | 16次请求均200/Go/cost0：child读、parent修改，原3测试红2→绿3且未改测试。业务用例通过后审计stdout因环境重连BrokenPipe，整体campaign仍FAIL；非作者独立核验业务/代码散列和红绿结果，不改写失败。 |
| 真实 Go 分文件修改 | 24次请求均200/Go/cost0：parent修stats.py、child修labels.py并实际跑3测试，parent原完整6测试红4→绿6，未改测试/README，原wait结果回父会话。整个campaign及清理成功。child得到父模型的修复提示，不宣称其独立发现算法。 |
| UI 与应用往返 | 真实密码认证/PG，1440/390/320无横溢/pageerror；原子任务往返/刷新零写。另1440/390实际点击返回平台→独立Research首页→原session及child，零导航写。样例数据明确标记；长结果原样Markdown展示仍待易用性改善。 |
| 撤权 | 实际PG禁用owner后，Research工具403、模型入口PermissionError、注册工具拒绝，无新增文件/effect/模型请求。child native failed attempt2、root仍paused，最终投影未完成；仅证明新操作边界，不宣称整树立即终止。 |
| 公开仓库实模 | 两次完整任务均FAIL，未产生补丁。第一次8次200、一响应未知、一次429明确容量拒绝；第二次18次200、两响应未知、没有429。未知提供方请求不自动重放。已另复现产品30秒模型请求截断；它对旧失败的因果仍须区分直接证据和推断。另修正审计pytest环境，不能让模型修操作员环境导致的警告。 |

非作者累计代码审计 SHA256 `103ca33c8c694f5cff75985ea7568bb173ed783ac6b97bfc5ac09d4c506064fb`；真实分文件修改审计 `1e35b226d96a683f2265bd4b168a30141c627c80cf937e0e82b6e103ee32a0b6`；往返/撤权索引 `2985d0b0a5b669347ba54234df6f33873c9bdf69460a8c8c7607ccfc070c4693`。完整脚本、截图及失败记录保留在云端 `/workspace/design-audit/research-session-subagents-20261028/`，无秘密产物经复核后随代码提供。

精选实际渲染：[桌面真实 Go 子结果](../../../docs/images/research-session-subagents/desktop-real-go-result.png)、[手机真实 Go 子结果](../../../docs/images/research-session-subagents/mobile-real-go-result.png)、[手机实际停止](../../../docs/images/research-session-subagents/mobile-child-stop.png)、[手机原子任务入口](../../../docs/images/research-session-subagents/mobile-original-child.png)。前两张来自真实模型分文件任务，后两张来自明确 SCRIPTED 的实际 PG/浏览器行为测试；不是用户部署地址。长文本视窗和原样 Markdown 的可读性尚未完善，不以无横溢代替视觉验收。

后续9630候选在公开仓库完成原父子分工、源码修复及206项测试，模型补丁由非作者独立复跑通过；该campaign仍因child执行一次被提示禁止的ls而FAIL。功能目标与指令遵守分列，详见[模型请求期限验收](../research-model-request-lifetime/verification.md)，不声称硬只读子权限。此前3次失败不改写。运行中的派发窗口可暂显待核对并由只读刷新恢复，尚非理想呈现。

待完成：子助手最终准确 head full CI、适用发布/main 门禁。未验证：默认首次启动、真实GPU/SSH、目标64GB/30会话容量、部署、任意同文件并发编辑、一般研究质量。忘记不删除旧聊天/摘要；旧会话更新配置、正常依赖获取、长结果展示与全站易用性继续原 roadmap。
