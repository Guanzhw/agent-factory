## Why

现 personal_ssh.probe 与 SSHProcessTransport 两处 select 管道代码不能直接用于原生 Windows，且 prepare 的阻塞写和部分清理 wait 没有统一时限。需要为这两个既有消费者提供一个窄的受控子进程管道交换能力，不引入另一套任务控制链。

## What Changes

- 新增 SSH 专用 bounded exchange 模块，使用 asyncio subprocess 管道并发读写，固定请求/响应字节上限及绝对期限，取消/异常均 kill、收尾、reap。
- 定义每次写与 EOF 前的同步 fresh guard 和取消传播；真实受控 Python 子进程验证 Linux 行为，Windows 实际 runner 另验。
- 本切片仅实现新模块及测试。两个调用点与 pinned argv 构造由 coordinator 后续集成，原 JSON/nonce、lease、原 operation/UNKNOWN 语义不迁入 helper。

## Capabilities

### New Capabilities
- `bounded-ssh-pipes`: 两个既有 SSH 调用点共享的有限时、有限字节管道交换。

### Modified Capabilities

无。

## Impact

新增 platform/agent_factory/ssh_exchange.py 与 platform/tests/test_ssh_exchange.py。基线 d3ec92f。无真实远端连接、凭据、PG、模型、GPU或新第三方依赖；不能据此删除原 Windows SSH agent/身份限制。
