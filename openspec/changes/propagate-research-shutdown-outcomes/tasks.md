# Tasks and ownership

- [x] 用户决定35秒后服务自行非零退出，允许中断未完成本地清理。
- [x] shutdown_design：应用owner闭合执行入口、共享deadline并保留原cleanup。
- [x] root：core可选完整关闭护栏及deployment非零终止策略。
- [x] shutdown_tests：真实生产入口子进程/PG/重启fixture。
- [x] root串行运行owner、真实进程PG、相关回归与独立core检查。
- [ ] 独立复核、静态/架构、精确head CI、更新Draft98和资源清理。

与#97历史分页、#103测试审计分支隔离。禁止合并、部署、付费或真实模型调用。所有未运行结果明确标记，不以返回错误代替进程退出证据。
