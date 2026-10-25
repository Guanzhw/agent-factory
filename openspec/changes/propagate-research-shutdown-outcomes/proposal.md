# 科研关闭结果与原操作收尾

## Why
原控制器close的False被忽略，receiver gather可能无限等待，科研执行生成的独立cleanup未完整纳入关闭。释放数据库或服务图时，原清理可能仍在运行。

## What Changes
关闭新科研执行入口，跟踪原execution与晚生cleanup，所有owner共用原35秒期限。期限未完成由部署进程非零退出；核心可选关闭护栏涵盖app、observer、native及依赖释放。用户已明确接受未完成本地清理被中断；UNKNOWN原身份与占用保留，重启不得重派发。

## Impact
科研owner生命周期、核心退出阶段可选hook、部署进程策略和真实子进程PG验收。不改变外部停止证明，不部署或合并。
