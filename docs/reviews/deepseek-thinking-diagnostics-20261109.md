# DeepSeek thinking 与聊天诊断修复验收

基线为 `7be1310`。目标是让普通对话直接呈现回复，真实 thinking 按发生顺序展示，内部事件留在独立诊断入口。

## 差异与修复

- 对照本机 DSH 0.2.2-rc.1、pi-ai 1.5.0 的实际页面与安装源码：该 OpenCode Go 模型在选择显式强度时同时发送 `thinking.enabled` 与 `reasoning_effort`。省略参数不能解释为关闭 thinking。
- Factory 对精确 OpenCode Go OpenAI 端点、`deepseek-v4.1-flash`、Chat Completions 补充 `thinking.enabled`。“自动”省略强度参数；low/high/max 保留用户选择。其他模型、端点、Responses 和存量配置不变。
- 流中的 `role` 是 OpenAI SDK 明确允许为空的字段。Factory 原来的严格检查会拒绝 null；现在交给原生 SDK 合并，保留对显式错误角色的拒绝和重复 assistant 的处理。
- 普通聊天移除逐轮原始事件，诊断移到“会话信息 → 诊断记录”。只有实际 thinking 或工具调用才产生过程入口，最终回复独立显示。
- 同调用的完整回执与结束事件一致时只显示一次；恢复、修订和状态不同的回执仍可查看。子助手结果只显示一份。
- 原生运行中的工具预留回执为 UNKNOWN/null；在同一 run、同一调用已有开始且无结束事件时，界面显示进行中的工具记录。终态缺失结束、明确 unknown 和其他调用的未知结果仍提示核对。

没有新增事件框架、执行层、数据库迁移或固定工作流；继续使用现有 Agno 会话、run、队列与流式回调。

## 真实提供方证据

测试使用隔离账户、数据库和工作区，以及已授权订阅；原服务和原会话保持运行。外部观察器保存字段、计数、规范化请求摘要与异常位置，未把凭据、原始流或思考正文提交仓库。

16 次最小 prompt 对照均成功，包括 default/high/max 与 DSH 风格 max+enabled。default 也能返回 thinking，证明“自动等于关闭”的判断不成立。

完整原生 Agent 提示与 23 个工具的匹配 hi/default 对照中，仅增加 thinking 开关，reasoning 从 0 变为 405 字符；归一化请求摘要相同。其他 default/high/max 对照的强度同时出现在系统指令内，不能当作仅改变一个 wire 字段的严格实验。

修复后的真实页面普通 hi 请求，raw → callback → parser → 持久事件均收到 167 字符 reasoning；后续 `how are you` 收到 123 字符 reasoning 与 64 字符正文。实际 high 工具轮完成退出码 0 和 7，页面正确区分成功与失败；max 长回复从部分正文增长为完整回答。

真实页面核对三层折叠、独立最终回答、会话信息诊断入口、390px 面板无横向溢出。运行中的真实命令只有一个工具记录，重复回执与未知告警均为零；页面 Stop 终止已核对的进程，刷新保持原轮次和停止结果。

最终补丁另完成文件创建、读取、页面预览与退出码 7；18 字节 API 下载与工作区原件一致。刷新前后两轮的 run、事件 ID 与模型请求数相同。该工具轮实际返回 59 字符 reasoning，其他未返回 reasoning 的阶段未生成思考内容。

## 自动检查与 review

- `npm run check`：通过，包含 lint、TypeScript 与 build。
- `python -m unittest discover -s tests -v`：最终 41 项通过，171.505 秒，退出码 0，使用可丢弃 PostgreSQL 与真实本地 HTTP/Agno 队列。
- `ruff check platform deployment applications tests`、完整工作树 Pyright、`git diff --check`：通过。
- nullable-role 回归在内存加载的原 HEAD 源码上准确失败；修复后的 7 项流式测试独立通过。
- 独立 review 覆盖精确模型策略、原生 SDK 合并、回执恢复和修订、进行中与未知区分、子助手去重；发现的两项回执/子助手问题已修正并复审。

一次完整测试曾在原生任务尚未完成时提前接受临时 unknown 快照，导致完成断言失败。等待条件改为已有的 `completedAt` 终态标记，保留完成、未知回执及不重放断言；针对用例与最终完整套件均通过。失败日志保留在仓库外。

## 证据边界

此前部分真实 high/max 请求以 ValueError 失败。临时观察器确认抛错位于 role 检查，但当时只记录字段计数，无法逐条还原被拒角色的值；nullable-role 修复有 SDK 契约与可复现回归支持，不把历史失败全部解释成强度参数错误。

自动用例中的 thinking、未知回执与断线场景是协议夹具，分别验证顺序、状态和恢复，不作为模型真实推理证据。真实模型是否返回 thinking 仍以每次实际返回为准。

构建保留既有空选择器与 bundle 大小警告，Windows 仍有 TLS/RST、未关闭 transport 和零活动请求的有界关闭警告。本次没有部署到原服务，也没有合并 PR。
