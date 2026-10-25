# 规划：科研服务关闭结果与未完成资源收尾

状态：Draft 已实现并完成首轮真实进程验收，见 [执行记录](../../openspec/changes/propagate-research-shutdown-outcomes/verification.md)。基于可信团队重构 PR #95 的合并提交 `246f06541b21915392a77555e24f3f617d34de9f`。
建议 OpenSpec change：`propagate-research-shutdown-outcomes`。

## 问题与结果

服务关闭时应明确报告控制器与清理是否完成，并让尚在运行的清理协程继续拥有所需依赖。当前 `close()` 已返回未完成结果，但装配层忽略它，随后移除服务关联。

- `apps/research/agent_factory_research/autoresearch_session_control.py:293-307`：等待上限为 35 秒，仍有控制器或清理任务时返回 `False`。
- `apps/research/agent_factory_research/assembly.py:144-163`：没有消费该返回值，shutdown 回调会释放 service graph。
- `platform/agent_factory/main.py:312-327`：控制 lifespan、observer/native drain 与共享依赖释放顺序。
- `apps/research/agent_factory_research/services.py:30-38`：关联释放后再次查找会新建空 graph。

忽略返回值已由源码确认；尚未通过本规划复现清理协程使用已释放 graph 的运行故障。

## 实施范围

1. 用现有有界等待结果区分已完成与未完成；若布尔值和明确失败路径足够，就沿用它，不为结果另建无消费者的类型体系。
2. 装配层消费关闭结果，在未完成时留下明确失败及原任务诊断，不能产生 clean-shutdown 成功回执。
3. 依据真实待清理协程的消费者，选择直接持有 graph 或延后释放；同一依赖只有一个明确生命周期拥有者。
4. 重启继续核对原操作的停止结果，不重新提交控制器意图。保留未确认效果及其资源占用。

## 验收

- [x] 真实 Uvicorn、隔离 PostgreSQL 和受控进程复现活动执行、正在清理、已完成三种关闭时机。
- [x] 让清理超过现有等待边界，验证未完成结果到达装配层；记录退出结果，证明仍在使用的句柄未提前释放、未创建空替代 graph。
- [x] 重启后恢复原 intent/effect 身份；在正向停止证据到达前不重复派发或释放容量。
- [ ] 运行控制器、应用装配、独立核心启动/关闭及原操作恢复回归。

取消回执与进程退出不能自动充当远程停止证明。保持有界关闭；本项不增加通用调度器、不自动重放 UNKNOWN，也不把等待改成无限。

## 顺序与待定项

建议早于多应用装配和多轮科研实施。用户已选择原35秒期限后由进程自行非零退出，允许中断未完成本地清理；不依赖外部supervisor。部署层采用非阻塞退出策略，原持久化操作为恢复依据。
