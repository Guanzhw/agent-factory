## Why
P5/D01 承诺的个人远端训练链尚未接通：当前 SSH 资源只检查连接/准备条件，研究实验 child 仍本机执行。成员的入口可能经过透明 TCP 端口映射，连接成功也不能证明具备原任务提交、恢复、取消与证据取回能力。

## What Changes
- 保留 Factory 原生 research root→实验 child；child 使用显式选择的 SSH 计算资源运行训练进程，模型与队列不迁往远端。
- 复用 SSH 凭据租约、严格主机身份、资源 lease、持久进程 custody 与原操作 ID；补 SSH 执行适配器和普通 Agent 原生外部等待结果接线。
- 提交响应丢失、控制器重启、取消与证据收集沿原身份，不新增任务重试、第二队列、凭据库或后台轮询器。
- 配置与验收区分透明 TCP 转发入口、实际 SSH 主机和集群执行约束；不默认 Slurm，不自动安装远端 runtime 或创建密钥。

## Capabilities
### New Capabilities
- `research-ssh-execution`: 显式 SSH 训练资源与现有研究 root/child、原生等待、停止证据和成果链的接入。
### Modified Capabilities
- 无已归档规格；复用现有变更中的 SSH 身份、process custody、delegated operation 和研究轮次约束，不复制其完整规范。

## Impact
拟涉及 core SSH/resource/process/external-wait 接缝、研究 setup/确认约定和精选证据。基线 `9454000`；移除 demo 的并行分支尚未合入，实施须基于其最终正式认证配置，不依赖旧开发 profile。此提交仅规划，无真实远端访问或产品改动。实际集群是否允许直接启动进程尚待确认；调度器专用提交不属于未经确认的默认实现。
