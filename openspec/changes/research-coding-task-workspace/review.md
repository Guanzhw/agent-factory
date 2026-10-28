# 独立方案审查

2026-10-28，非作者 reviewer `coding_minimal_design_check`：**方案 PASS，可以开始实现；不是产品验收通过。**

- 产品基线：`da2b6ca0ef0bf60062721b2c0a1755d3434e8da2`。
- 完整读取 proposal、design、spec、tasks；复审四稿 aggregate：`b18d6857cd96fba8f88a0d5ef7c33265aabab1b8c48238ac9ac8f9fbe053ced7`。按上述顺序，将各仓库相对路径、NUL、文件 SHA256 十六进制、LF 拼接后取 SHA256；不含本文件。
- 独立运行 `OPENSPEC_TELEMETRY=0 openspec validate research-coding-task-workspace --strict`：PASS。结构校验不替代下述行为审查。

## 发现与整改

初稿允许用环境 `PYTHONPATH` 准备项目，但现有命令环境会清除它。已要求移除此未接线路径；修订明确“预定 venv PATH 启动 → 会话内取得仓库 → 操作方安装固定依赖和指向该副本的 editable → 显式继续”，并核父/测试子进程真实导入路径。复审 design SHA256：`26a2b06a6e0d6e343e8358dc2247e9d4a2a8e6824d77d0b9b55ba368ddca4d59`。该问题已解决，无剩余方案阻塞。

## 审查结论

- 范围对应真实失败：45,599 字节源码读改拒绝、正确 query 的大文件漏搜、完整测试约 35 秒但研究操作在约 31 秒结束为 UNKNOWN。已核直接测试、原生回执与正确查询补验；旧错误 query 不计入漏搜证明。
- 简洁性 PASS：实际 read JSON 为 47,442 字节，现有 65,536 字节返回预算足够；不先增加分页、文件魔数、执行器、仓库管理器或重复结果组件。命令输出与会话投影本片不抬高。
- 时间路径完整：除研究 route/setup/tool 三处外，已纳入共享 `EnvironmentLimits` 的 30 秒构造上限和正常 `Settings.from_env` 接线。保持默认及其他 adapter 自己的实际时限，要求回归而非只测直接构造 Settings。
- 用户路径可验：真实公共仓库、来源/目录/commit 回执、隔离依赖准备、失败复现、自主修复及完整测试串在原会话。预配置人工步骤已明确，不宣称任意项目自动配置。
- 控制语义保留：纠正在下一模型请求纳入；明确停止核实际受管父子进程；服务重启后 GET 不执行、核原操作后显式继续；UNKNOWN 不自动重放。现有超时证据不抵扣后续主动停止与重启验收。

实现后仍需完整累计 diff 非作者审查、真实 Go 自主任务、独立文件/进程及 PostgreSQL 验证、桌面手机浏览器和准确 head CI。官方参考修复通过不是 agent 解题；脚本模型不是实模。无 GPU、目标硬件容量或部署通过声明。本审查不执行 GitHub Approve/Ready/merge，也不改变已有发布待确认状态。

## 环境前置窄复审

同日，代码基线仍为 `da2b6ca0ef0bf60062721b2c0a1755d3434e8da2`；在已提交方案 `e15a262c675521de25c35975e610017b564ec383` 上复审四稿环境准备差异。新 aggregate：`594bb17887e5a30735e460ced5dfbf5f8fb342ce77935267d5f46256907b16fc`，计算规则同上；独立 strict validate PASS。

**本地副本路径方案 PASS。** 已读 `qa/live/public-git-preflight.json`：等价净化环境的官方 Git `ls-remote` 预检在 5.041 秒返回 exit 128/连接失败；它不是原生 `research_run` 回执，也不是已执行 clone 的结果。proposal 的含混表述已改正。公网 clone 留为 BLOCKED，公网依赖获取/网络能力未通过，不用本地副本或缓存安装抵扣。

允许继续的验收路径是操作方明确提供已核官方来源/commit 的副本，助手经原生工具核实际 pwd/origin/HEAD/源码 SHA，操作方准备指向该副本的隔离 editable 环境，再在同一会话显式继续。它仍在既定“仓库副本与已准备环境”范围内，不新增产品 fallback、仓库管理器或网络配置。

预检不能单独判定平台网络策略禁止连接，也不能证明产品清除正常代理配置必然合理；该归因尚未确认，可独立只读调查。本次复审不把当前环境阻碍固化为永久安全边界，不授权代理透传、网络设置修改或绕过拒绝。产品代码尚在作者实施，此次只审四稿差异，未审查或更改并行产品修改。
