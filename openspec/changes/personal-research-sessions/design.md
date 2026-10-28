# Design

## Context

动机见 proposal.md。基线 main 3ec76ad 使用 Agno 3.1.0。ResearchAssistants 已提供 owner 唯一身份；ApplicationRuns、Store、模型分派依赖 task_id = 原生 session_id，不能直接把长期助手 ID 塞入该字段。默认队列允许两次尝试，已有 effect 回执和 run_cli_process；原生 CodingTools 的取消测试失败与平台进程控制通过是不同对象。

## Goals / Non-Goals

首片打通真实多轮纵向链，复用原生 Agent 推理/工具循环，应用代码只管持久会话、上下文和已有执行边界的接线。保留旧工作流/项目/QA/任务的读写兼容。

不迁移框架、不升级依赖、不实现通用 agent harness、自动长期记忆、完整 OS 沙箱、远端 GPU 接入或新的权限角色。自然语言停止边界供模型遵循，时间/工具次数等机器限制另行执行；BYOK 不冒称 token/金额硬上限。

## Decisions

1. **逻辑会话与任务分离。** Research 应用表保存稳定 assistant/owner、目标和停止边界、有界消息及原 task 引用；每次显式继续使用既有 ApplicationRuns admission，仍是独立 task/native session。复用现有连接选择与安装材料生成，不让用户手填 adapter/plan/Workflow。改全平台 session invariant 的方案影响过大，舍弃。
2. **原生自主循环。** 新模式不选择 ResearchWorkflow。应用注册精简文件读取、搜索、精确编辑、命令运行和共享证据工具，交给 factory-executor Agent 自主决定次序。模型继续通过现有 owner 模型连接分派，工具继续校验当前权限和 effect。
   2026-10-28 核查 [Go 官方端点](https://opencode.ai/v2/docs/console/go/#endpoints) 已提供 `/inference/go/openai/v1`；现有客户端只给旧两条路径附加自身标识和稳定 session header。本片将新明确端点纳入相同 header 规则，保留旧配置，不改模型/计费选择或启用回退。
3. **纠正在下一请求边界加入。** 现有 ApplicationRuntimeRegistry 的 owner 回调新增窄 before_model 接点，位于当前权限确认之后、provider 请求与计费取证之前，覆盖同步、异步、流式/非流式 provider 请求前；不塞入会在响应后反复调用的授权检查。消息先事务持久化，再回执；稳定 ID 防同一 messages 列表重复，重试不能因游标丢消息。“已纳入请求”不代表模型已遵守。原请求和工具无法瞬时改写。若本轮直接结束，未纳入纠正保留到下一显式轮次；超过容量时拒绝派发，不能删除纠正或误标已纳入。
4. **有限上下文，明确阶段。** 目标/停止边界/本轮指令/未解决原操作始终保留，先提供有界的已完成轮次结果与纠正，不把工具日志伪装用户发言。超过界限明确拒绝新一轮并保留全部历史；不悄悄截断或无限拼接。后续单独实现摘要及原模型分派契约兼容验收。
5. **执行环境显式启用。** 首片的本地 coding workspace 仅在部署明确配置研究目录时启用；按 owner/session 划分目录，文件工具拒绝越界和符号链接。命令复用 run_cli_process，无环境秘密继承，有时限/输出限额、取消和进程组回执。命令拥有部署 OS 用户权限，cwd/路径校验不是 OS 沙箱，不能作为敌对多租户隔离声明；部署者必须选择符合信任边界的独立执行环境，当前不更改网络/隔离设置；任意命令仍可能读取 OS 用户可读的其他文件，不能宣称命令层跨租户隔离已通过。未配置时界面说明缺项，不默认在服务源码目录执行。
6. **恢复从原操作核对开始。** admission requestId 幂等，同会话仅一个未完成 turn。先事务保留 owner/session/turn/稳定 application request ID，再提交事务，最后调用 ApplicationRuns.start；工具和上下文只通过原 task.request_id 查可信 reservation 并核 owner/application pin，不信任任意 inputValues.sessionId。丢回执或 reserve 后退出只能查询原 request，不把404当允许重发；首片显示待核对，不自动补派发。任务每次进入原生运行时持久记录尝试；重复尝试若已有写/执行 effect 且不能证明原工具历史完整恢复，停止自动模型调用，保留原 task/effect 核对。UNKNOWN 同样阻止本任务和新 turn；DONE 回执不能单独证明可重放。GET/刷新/服务重启不自动提交新 run。已完成轮次可显式继续同一逻辑会话。
7. **现有共享授权。** 证据工具读取 application_content 中明确 team 发布的研究证据，每次校验当前访问与撤销，不分享私人会话/凭据。返回来源引用，保存被读 source IDs；每次后续模型请求/新轮次复用上下文前复核这些来源，撤销则阻止受影响上下文继续，不只是禁新 read。跨助手自动留言和私有记忆仍沿用既有能力，首片不扩展编排。
8. **真实 UI。** Auto Research 主页保留项目与历史入口，增加“研究会话”。会话页以目标、对话和真实工具/任务状态为主，技术详情按需展开。保留底座应用入口/返回，手机就地错误、重复点击、刷新和后退前进有明确行为。旧 UI 候选不整体导入。

## Risks / Trade-offs

- [服务硬退出无法确认孤儿命令] → 显示原操作未确认，禁止盲重放；不把取消接收当停止证明。
- [本地命令不是 OS 沙箱] → 无默认启用、部署要求显式、子进程不继承服务秘密，测试仅临时数据；安全隔离和真实个人主机单列未验证。
- [3.1.0 原生 task 会话不能跨 turn 自动继承] → 应用有界上下文保留，不误称已接原生长期 memory；后续摘要独立 PR。
- [当前公开资料有陈旧 Research 删除说法] → 本片只修直接相关文档与 OpenSpec context，实际装配为依据。

## Migration Plan

新增应用表与可选设置，不改旧 task/session ID、默认 core-only 装配及既有数据。先 Draft PR、独立累计 diff 审查、PG/进程/真实浏览器及有限模型验证，再依授权合并。回退部署代码保留新表和工作目录，不删除数据；旧任务保持可查。

阶段一为本提案首片；阶段二处理长会话摘要、恢复核对的更充分可操作闭环、已有异步助手消息与研究会话的授权整合；阶段三完成“应用/我的任务/我的资源”和所有管理子页易用性整改。每阶段独立 spec/小 PR，不以首片宣称整体 UI 或自主研究质量验收完成。
