## Context

两个实际消费者：probe 最多 8192 响应字节；SSHProcessTransport 请求最多32768字节、响应最多1MiB。当前 helper 在 stdin EOF 后才解释原请求，取消时不得先关闭 stdin 使未确认请求完成。远端进程 custody 与本地 SSH 客户端 I/O 是不同责任。

## Goals / Non-Goals

目标是用一个有界管道交换替代两处 select，保留 fresh authority、无新重试和原身份。非目标包括通用进程树监管、shell执行、JSON协议处理、自动安装、凭据后端、Windows agent实现及真实远端验收。

## Decisions

- 单一公开同步入口 `exchange(argv, payload, *, env, max_output, before_effect, cancelled=None)`；输入是既有 pinned SSH 参数构造产生的 argv 和有限 bytes，stdin写块4096，响应逐块累计检查。stderr DEVNULL，无shell；helper不记录字节或argv。
- 入口先核payload<=32768和合法响应上限<=1MiB，创建统一绝对工作deadline（默认30秒）。spawn、写、读、正常退出共享剩余时间，不能各自重置30秒。probe空输入允许；JSON/nonce和响应码仍调用方解释。
- 每次调用在当前已有同步worker内使用私有 asyncio.Runner；Windows明确使用Proactor loop，POSIX使用默认loop。不新增 reader/writer 线程，不使用communicate。loop内使用公开低层subprocess transport/protocol以便在deadline后关闭owned管道且独立观察process_exited，不依赖私有 `Process._transport` 或无限EOF等待。
- 仅少量 I/O职责：protocol累加有界stdout、记录EOF和退出、提供写端背压通知；协程写payload、每块write与EOF前执行同步before_effect、等待响应EOF与退出。完整缓冲最多响应cap加单次回调块（超限立即终止，不返回截断成功）。spawn前也fresh检查。
- cancelled是现allocate_bound已有threading.Event的窄输入；loop内有界短间隔检查，发现取消即中断传输。guard只能同步；不得把awaitable当授权通过。
- 异常/超时/取消先kill本地子进程，再close transport管道，不先flush/EOF。总工作deadline外最多5秒清理额度用于reap/结束owned asyncio任务；无无界wait或join。若OS未确认退出，返回明确cleanup错误，不能声明成功清理。任务全部cancel并收回，Runner退出不留ownedI/O线程/task。
- 原请求完整发送后丢回执仍交原消费者按UNKNOWN处理；helper不submit重试、不推断远端停止。清理只针对已拥有的本地OpenSSH进程，不添加孙进程扫描/kill树。
- 后续集成必须保留worker引用，外部async取消设置event后等待本helper清理结果再传播CancelledError；仅cancel asyncio.to_thread await并返回不足以证明worker已清理。本切片不修改消费者。

## Risks / Trade-offs

低层protocol比两个select循环稍多生命周期代码，但避免Windows匿名pipe select与清理时无限等待EOF。仅服务两个明确消费者，不做可插拔协议/传输框架。真实Windows CI验证Proactor路径，sys.platform mock不算。Windows身份/agent/private_directory/known_hosts路径仍单独阻塞。

## Verification

真实本地Python子进程同时写输出和读输入；不读取stdin/输出超限/退出非零/EOF后存活/guard写中拒绝/取消等有限实验。检查原子进程退出与无新增线程。继承stdout的短命孙进程仅检验关闭owned pipe不无限等EOF，不提供通用树清理保证。Linux实跑；Windows留待runner，不能标已通过。
