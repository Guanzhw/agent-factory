# Verification

基线 `da2b6ca0ef0bf60062721b2c0a1755d3434e8da2`；本轮已验产品 `b8718338d49f3a6e68ff09e104f1a817fa005cd6`，tree `d1199a0663fd7c809644b30a1dd0110b69dfb85f`。保持 Agno **3.1.0**。后续提交只补验收记录和截图；准确提交的完整 CI、发布与部署另行记录，不能由本页推定。

## Real model task

使用官方 pytest-dev/pytest-asyncio 的公开基线 `2188cdbbf7b47e653957d3f39aeb7d4d0de80bf4` 和公开回归测试，操作方准备隔离副本、固定依赖与源码路径。模型未收到修复答案，也未访问参考修复副本。

真实 Go `deepseek-v4.1-flash` 自主核来源、复现失败、读取 45,599 字节源码、搜索及精确修改。最终只读验证得到目标测试 **1 passed / 0.50 秒**、完整 `coverage run -m pytest` **206 passed / 35.24 秒**，均 exit 0；验证前后 tracked 源码树一致，全部官方测试保持原字节。源码由 `41a7b8e0741eac47470096245e07e9baf8ccb3a7556bfbb77b05076010c3a2d1` 改为 `d4223f73f89cdbe8f042b8338dc15bd3a2cd4ed92dc405060757038f295c2545`。

共 **27 个真实模型请求、4 个显式轮次**，包含实际摘要后继续；最终 idle/completed、所有 effect DONE、未决请求 0。四轮分别是观察、调查到工具预算耗尽、继续修复、独立只读验证；每轮 8 工具额度额外造成一个修复续轮，不能把四轮都归因于该额度，也不能称一次目标已经完全无人干预。

该证据使用真实 ASGI/native PostgreSQL、文件和进程，经测试专用内存 Go 转发使用现有订阅。它不证明未经修改的 CLI 网络通道、自动联网安装、真实模型停止重启或任意仓库研究质量。请求保留原产品 4,096 token 参数、provider 标识和稳定 session header，无模拟模型答复、额外计费或 provider fallback。

## Separate verification boundaries

| 范围 | 实际结果与限制 |
| --- | --- |
| 当前正常 CLI / PG | `b871833` 中同一轮先搜索缺失文件，收到可读失败后正确搜索真实单文件和目录，正常完成；4 个脚本模型请求，无 `protected-failure`，原失败事件保留。不是实模决策证明。 |
| 当前浏览器 / 在途去重 | 真实密码登录、真实双击只发一次 POST；在途相同 requestId 重发得到同 task/turn/run，短命令只追加一行、一个 effect。2 个脚本模型请求。桌面/手机另用原样历史回执作只读呈现 fixture，核完整测试末行、未知状态、继续入口及原任务导航；没有导入原任务详情或重跑历史测试。 |
| 前一版本长链 | `afee072` 的正常 CLI/真实 PG/脚本模型完成完整测试 206 passed / 36.12 秒、中途纠正在下一请求纳入、实际父子进程停止、服务 SIGTERM 退出重启后 GET 零执行、显式继续再次 206 passed / 35.61 秒。真实超时产生 UNKNOWN，第二次服务重启后原 run 不变、新请求 409，无重放。22 个脚本模型请求。此行不是 `b871833` 上的新重启执行。 |
| 当前便携与反例 | 非作者在准确 `b871833` 跑 39 项通过、0 skip。额外实际临时文件/合成 store 证明写后 fsync 失败保持 UNKNOWN、后续写被阻止；CLI 已派发即使 stopped 仍 unknown；当前授权失效阻断，原失败 call 只返回回执，新合法 call 可用。不是 PG 重启或 OS 强隔离证明。 |
| 静态与完整审查 | 作者 Ruff、Pyright 0 errors（14 项 Linux 缺 Windows 源提示）；非作者审累计 16 个文件及简洁性，OpenSpec strict、diff check 通过。协作旧失败断言与项目环境说明已整改复审。 |
| 真实模型补丁质量 | 另一独立 Go session 审查实际生成补丁；独立短函数反例核已关闭循环、正常清理、RuntimeError 警告并关闭、其他异常仍传播。未读取参考答案，未替模型重写补丁，未把一次修复当一般研究质量证明。 |

## Review and retained failures

累计代码审查 base/head 如上，diff SHA256 `befd4ea06b7b9bcdec60e24dbc4a8e8a86729a42efd2f728b48ef2d5ebd6e9d8`，研究工具源码 SHA256 `94f43e114217634a22821a326ca82cf63d62fe701833f5a874889f6cd9ba2fcc`。非作者报告 `review/independent-code-review-b871833.json` SHA256 `b3b3d9bf982acb153c020d302f3ff9fab6c921af9a3faaf65ff23c011fbb25a8`。Go 参与累计审查、环境排错、窄实现建议及独立复审；其不准确建议均经源码/反例核对后否决，不等于 GitHub Approve。

原失败均保留：文件/时间限制、真实同轮工具误判、单文件搜索、editable 测试发现错误、旧协作断言、QA JSON/信号退出断言、首轮完成预期以及 24 请求预算截断。曾有 HTTP 200 但只产生推理而无审查结论的响应，没有计作有效 review。所有实模重验前均核原请求已结束，没有未知请求并行重发。

执行环境证据根为 `/workspace/design-audit/research-coding-task-20261028/`：真实模型 `qa/live/run-1793212152962745911/`，当前 CLI/浏览器 `qa/browser-followup-1793211743899300155/`，前一版本长链 `qa/postfix-1793208792601667151/`，独立审查 `review/` 与 `go-work/`。这些是可恢复的执行环境文件路径，不是公开预览地址；精选安全截图见[图示说明](../../../docs/images/research-coding-task/README.md)。

## Remaining scope

研究工具净化环境的 Git 预检失败，而同一 Git 在正常云 shell 成功；具体代理/CA 原因未逐变量验证。预置副本与缓存依赖不抵扣公网 clone/安装。未验证 GPU/SSH、Windows 本地命令、64GB/30 活跃会话容量、生产部署或完整 OS 隔离。下一片优先处理实测 8 工具中断与跨轮重复读取，复用现有预算和 Agno 生命周期；长期个人记忆、临时子助手、完整团队编排及全站易用性仍需后续交付。
