## Context

现 personal_ssh.probe 与 SSHProcessTransport 是两个实际消费者，响应上限分别8192字节/1MiB，请求最多32768字节。项目Python>=3.12，官方明确[os.set_blocking新增Windows pipes支持](https://docs.python.org/3.12/library/os.html#os.set_blocking)。无需select、私有asyncio loop或reader线程。

## Goals / Non-Goals

一个窄的同步字节交换，保留原spawn/Job/凭据生命周期所有权。非目标：新spawn框架、协议parser、第二执行/恢复控制链、通用进程树监管或Windows凭据实现。

## Decisions

- 单入口 `exchange(process, payload, *, deadline, max_output, before_write=None, cancelled=None)`。process由现pinned SSH/受控Windows Job创建层拥有，带stdin/stdout管道；deadline由调用方在spawn前计算monotonic()+30。argv/凭据/JSON不进入helper，spawn前fresh由原调用方保留。
- helper接管该次调用的管道交换及本地process收尾；创建层仍负责Job/凭据资源结束，不能在exchange仍运行时提前释放。调用方必须在spawn后立即进入helper，或自行处理进入前失败。
- 入口try/finally包含输入验证、os.set_blocking(fd,False)和全部I/O。payload最多32768，max_output为1..1MiB。单轮stdout最多读取65536且不超过剩余额度+1，stdin最多写4096；两端轮流推进，避免任一端饥饿。无进展才用cancelled.wait最多10ms（没有event则time.sleep），不是busy loop。
- 只将BlockingIOError视为暂不可用，不把其它OSError吞成重试；真实零长度read才是EOF。Windows no-data/短写/EOF行为必须真实runner验证，不能猜errno兼容。输出一旦超上限立即失败，不返回截断成功。
- 每轮检查deadline/cancel；每次实际write与关闭stdin发送EOF前执行同步before_write并再次检查deadline/cancel。同步guard或OSspawn自身不能被抢占：其已有调用方须保证有界；本helper只保证返回后期限检查阻止继续effect。
- 成功必须完整发送输入、收到stdout EOF及poll确认exit0；EOF后进程继续存活仍受原deadline限制。读取结束不等于进程退出。
- 所有失败/取消先kill仍运行的本地进程，再进行最多5秒wait，最后关闭owned管道（stdin未写Python缓冲，全部走os.write）。不得在kill前用EOF/flush完成未授权请求。process已退出则直接reap；cleanup失败抛明确错误保留原因，不能宣称成功。没有无限wait、read线程、asyncio task或loop shutdown。
- stdin/stdout继承给短命孙进程的测试只证明读端不会无界等EOF，不新增树清理。正常系统OpenSSH通过原禁用Proxy/Control配置运行；Windows Job由其原启动层拥有。
- 消费者集成时async取消必须设置原cancel Event并等待持有的worker清理后再传播，不能只cancel to_thread的await就视作worker完成。原operation收到未知回执仍只inspect，不重submit。

## Verification

真实Python子进程覆盖双向大流、短写/暂不可用、输出上限、无人读stdin、EOF后存活、非零退出、写/EOF前撤权和取消及实际reap。Linux先跑，Windows CI另跑同组pipe用例；不将平台mock或纯helper成功认定完整Windows SSH支持。

## 既有消费者集成接缝（coordinator 实施）

1. `personal_ssh.probe` 在 lease 校验和 spawn 前创建30秒绝对deadline；spawn前 `lease.validate()`，exchange每write/EOF再次调用同一fresh lease校验。inspect用空payload，prepare保持原nonce/root/action JSON加换行；响应仍8192上限。原nonce、ok、directoryExists、代码/JSON/换行校验及SSH_CHECK_UNCONFIRMED映射仍由probe负责。exchange返回已确认exit0的完整bytes，成功后仍校验lease。Job/临时身份文件只在exchange清理完成后释放。
2. `SSHProcessTransport` 保留request schema/MAX_REQUEST_BYTES编码、lease_for(action)、原pinned command，spawn前创建deadline并执行fresh；将同一deadline/payload/MAX_RESPONSE_BYTES交exchange。每write/EOF的guard组合lease.validate和before_effect，成功后再次lease.validate再解析JSON。原operation/receipt解析、UNKNOWN和归档均不移入helper。
3. `SSHProcessProvider.allocate_bound` 保留原同步fresh回调与取消Event，并保存明确的worker Task。正常await使用shield防止取消丢失worker引用；取消后set Event，将其通过显式 `cancelled` 参数从exchange调用传至实际管道read循环（只在write fresh里检查不够）。等待同一个worker完成kill/reap/close才传播原CancelledError；重复取消仍只标记同一Event并等待原worker，不创建另一次任务/submit。
4. cleanup失败不得吞成普通取消。原worker若报告SSHExchangeCleanupError，向上报告该错误并保留取消/原错误cause；正常因cancel Event退出并已清理则传播原取消。不能catch所有异常然后假定清理成功。所有真实与测试exchange实现统一显式 `cancelled` 参数；不使用签名反射、TypeError重试或动态fallback。
5. 集成验收覆盖async cancellation在stdout等待期间，验证caller返回前worker已结束且process已reap；保留既有部分写/EOF前撤权和UNKNOWN不重派用例。模块单测不能替代这项调用生命周期测试。

A nonzero local SSH exit keeps the existing transport protocol rejection (`SSH_PROCESS_PROTOCOL_INVALID`) at the SSHProcessTransport boundary; the low-level exchange reports its subprocess error. This narrow mapping must not catch cleanup failure or turn an unconfirmed operation into stopped proof. Real wrong-host-pin testing must still prove no remote operation.
