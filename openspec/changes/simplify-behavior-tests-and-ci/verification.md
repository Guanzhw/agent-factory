# Verification

状态：实施中，尚未完成验收。

基线为 `3e206920b8ea86598fca35d3cedcd80dfbdf160d`，完整 CI：[40078129086](https://github.com/Guanzhw/agent-factory/actions/runs/40078129086)。此前 PR95 的 fast 和本地完整数据仅作历史参考，本次比较使用新的基线及最终运行。

## Before

- Linux 普通完整执行：3201 项，2620 成功、581 跳过、零失败/错误；执行 205.837 秒，job 244 秒。
- Windows 普通完整执行：3201 项，1978 成功、1221 跳过、1 失败、1 错误；执行 217.033 秒，job 316 秒。两个失败分别为隔离依赖缺失 pywintypes 和真实 MCP 调用的 UNKNOWN，均保留原始日志。
- Web：两种系统均 61 文件、699 项通过；Ubuntu job 37 秒、Windows job 77 秒。npm cache 分别命中/未命中，不能将差异归因于代码。
- 基线完整 PostgreSQL 尚在执行。

## Local checks

- 五个 Python 候选模块同一 Windows CPython 3.14.3：37 项（36 成功、1 Docker opt-in 跳过）变为 34 项（33 成功、同一跳过）。单次执行 4.648→4.420 秒，不宣称稳定速度提升。
- Node 24 完整 lint、TypeScript、构建通过，60 文件、695 项通过。目标前端集三次新进程中位数为 6.282→6.328 秒；改善的是断言价值与抗结构变化能力，此处没有速度提升。
- 原 PubMed 测试漏过“先请求后拒绝”的反例，连接 transport 后捕获；公共检索测试捕获共享锁被绕过。前端 class/属性顺序改变仍通过，历史默认展开时失败，生产文件恢复原始字节。
- checker 10/10，真实 106 模块依赖图通过。官方生产和完整 npm audit 均为 0；第一次完整审计 TLS 失败记录保留。
- 真实 Chromium 的 configured/bind-loss 三次均通过，本地中位数 4.684 秒；全部七个 desktop 场景也通过。每个短场景只配置/绑定一次；丢 ACK 后读取原回执而不重发。缺 Playwright、Chromium、构建及非法空场景均失败。
- Windows 核心夹具恢复必要 pywin32 路径后，诊断 copy probe 由 pywintypes 失败变为通过；本机 symlink 权限不足，真实 symlink 路径仍由最终 GitHub Windows 验证。
- MCP 夹具共享单个 SQLite DBAPI 连接的缺陷实际复现为 90 次中 1 次错误；文件数据库独立池连接后 90/90，通过时保留两个并发连接及原 UNKNOWN 语义。
- 独立审查未发现未解决问题；独立定向复跑 Python 33、Composer 14、checker 10 项通过。Windows 增量另行审查并重跑 31 项，26 成功、5 原有 POSIX 跳过。

## Pending integration

最终完整 CI、普通成功 ID 逐项对应和前后 job/阶段时间对比尚待完成。原始日志由维护者本地保留；最终在此记录公开运行链接及实际结果。浏览器 API 为合成拦截，显式外部服务/容器 opt-in 仍按实际执行情况报告。
