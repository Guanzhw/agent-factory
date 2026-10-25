# 验证记录

独立云端worktree `/workspace/agent-factory-shutdown`，原规划head `9e026e979dffc16a625dc7773fe6986d03bef3e8` 正常合入main `9a933aa8aadda1b80b216cf67f399974690c6fc6`，未覆盖其他分支。4 CPU/16 GiB，Python3.12.14/Agno3.1.0/Uvicorn0.54.0，锁文件未变；首次测试复用history的同锁interpreter并显式设置本worktree import roots，随后本worktree `uv sync --frozen` exit0独立安装。

## 用户决策与边界

用户明确选择原35秒期限后进程自行非零退出，允许未完成本地清理中断。部署层注入退出策略，core库没有硬退出默认；核心只提供可选护栏，使app/observer/native及依赖释放都处于期限内。线程Timer可处理事件循环同步sleep阻塞，不是持GIL C扩展下的硬实时保证。

## 已运行

原始命令JSON与日志在durable `/workspace/scratch/shutdown-review-20261024/`，自建server/child均按持有Popen精确回收，无外部模型/账号调用。

| 检查 | 结果 |
| --- | --- |
| `unittest test_research_shutdown_owners -v` | 5通过/0跳过，exit0：原cleanup、晚生cleanup、receiver抗cancel、completed、缺fatal启动拒绝 |
| `unittest test_research_shutdown_postgres -v` | 3通过/0跳过，75.168s，exit0；真实production main、Uvicorn、PG及父进程持有的合成child |
| 活动执行关闭 | 原child停止，依赖安全释放；Uvicorn正常SIGTERM按其0.54实现重发信号，实际-15，且有完整关闭日志 |
| 已完成执行关闭 | 原receipt保持，不再派发，完成关闭 |
| cleanup超过35秒 | 原期限未改，断言真实退出码1及34.5≤耗时<55；退出前34s依赖仍可读，无提前释放；同PG重启保持effect UNKNOWN、task/run/control身份与容量，新请求受限，派发仍一次 |
| `unittest test_research_shutdown_policy -v` | 2真实子进程通过/0跳过，exit0；测试Timer工厂断言生产参数35后缩短时钟到0.05，实际同步阻塞仍exit1，正常关闭取消timer后exit0 |

首轮PG每case日志/事件/child身份保存在`process-first/`，其observations仅记录最终generation；首代fatal1及时间区间由当轮实际断言确认。后续fixture增加per-generation结果记录，不改断言或时间，不冒称首轮已保存具体elapsed。

首次Pyright引用另一worktree interpreter但本地配置venv缺失，exit1/570 missing imports；这是静态环境解析失败，已安装本worktree锁定环境，待重新运行。尚待相关控制器/服务回归、独立core、最终静态及exact CI记录。

## 不外推

进程退出不证明外部原操作停止；合成child与UNKNOWN重启证明不等于真实ORX/远程供应商停止协议。未部署、未合并；PR保持Draft。#97和#103成果另branch独立审查。

现有service/controller/receiver70项初跑68通过、2错误：旧Harness autoresearch Mock未声明新真实接口cleanups，修正Mock(cleanups={})，未修改运行时代码或原断言；两项targeted结果另录。

锁定本worktree环境后Pyright 0 errors/0 warnings，exit0；原两项fixture修正后targeted2通过（1.001s）。初轮错误记录不删除。

既有真实native科研/外部session PG回归6通过/0跳过（35.399s），exit0，包含原请求恢复、取消正向停止、UNKNOWN hold和原parent暂停/恢复。见shutdown-native-pg。

最终Ruff、Python架构边界（0 violations/0 coverage gaps）及OpenSpec strict均exit0。

独立核心wheel安装/实际loopback启动/干净关闭/临时DB清理通过（shutdown-core-install，11.829s，exit0），验证可选部署护栏不破坏无research核心安装。
