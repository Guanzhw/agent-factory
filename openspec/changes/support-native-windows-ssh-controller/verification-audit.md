# 2026-10-26 独立审计整改记录

整改基线：`94c59e5954f5acacb039a73fa3332381fd542fe2`。方案提交
`036c6087f112b0c399677c9a39a9be95b2dcf844` 已由非作者审查通过；历史 installed
失败和 `445a2ce` 的成功保持原范围，本记录不把它们改写为整改后验收。

## 失败回归与实现

在旧生产实现上先加入回归：16 tests 产生11个失败 subcases，分别确认 broker
与 ASKPASS 自己的六秒预算、仅密文删除失败关闭共享 manager、POSIX 空格/引号
路径被 OpenSSH `-o` 再解析的问题。原 deadline 到期、pipe/process 清理失败等
拒绝路径仍保留。POSIX 缺陷来自早于104的 `67ffb007`，137只是新增复用消费者。

实现使 broker/helper 使用同一 caller/lease 最小绝对期限。helper 收到的是非秘密
`FACTORY_SSH_DEADLINE`；Python 3.12 的 monotonic 时钟为 system-wide，不能重置成
新的 duration。[Python 官方说明](https://docs.python.org/3.12/library/time.html#time.monotonic)
密文目录残留仍抛清理失败并占用 slot；活进程/broker/pipe 清理不确定仍关闭新 admission。
共同 argv 收到平台凭据参数；POSIX 固定 child cwd，并显式传入该 lease 的 agent socket。

首次修后28项运行中，27项通过；新增 file-only fixture 在第二 owner 进入后立即
离开 scope，正常触发了 broker 取消。仅修正该 fixture 等待原 broker 完成，再检查
第二 owner 可用及保留 slot 上限；没有改变生产取消或期限规则。

## 已执行检查

- 定向94 tests，0 skips，4.489s，PASS：`test_windows_ssh_credentials`、
  `test_ssh_command`、`test_ssh_exchange`、`test_ssh_process_provider`、
  `test_ssh_process_paths`、`test_ssh_tool_factory`、`SSHOperationProjectionTests`、
  `SSHPersonalTargetTests`、`SSHLaunchPreflightTests`、`PersonalSSHTests`。
- 全树 Ruff PASS；Pyright 0 errors、14个本机缺 Windows API source 的 warnings。
  使用既有共享依赖环境，未安装或变更依赖。
- Python architecture：518 modules，0 violations，0 coverage gaps。
- OpenSpec strict validation 与 diff whitespace 检查通过。

精确实现 `94ee7cd1587fd3d63926f0495832b6e25921540f` 的串行本机验收：5 tests、
0 skips、0 failures/errors，17.765s，PASS。使用已存在的 loopback SSH 工具与
PostgreSQL 17.11；测试前后确认新增临时数据库、存活测试进程和 fixture 目录均为零。

| 检查 | 实际范围 |
| --- | --- |
| `PersonalSSHLiveTests` 三项 | 真实 RSA/ECDSA/Ed25519 enrollment、共享调用保留 owner 凭据及撤回、错误 host pin 在远端操作前失败。 |
| `SSHProcessLoopbackTests` 一项 | 从当前源码建立独立 core wheel，经过非22端口 TCP 映射运行真实 Linux helper，检查原身份、output、cancel；CPU-only。 |
| `SSHNativeProcessTests.test_hard_kill_paused_controller_preserves_original_helper_and_run` | 真实 PostgreSQL/native worker 与 controller 硬停，恢复原 helper/run；此用例 SSH transport 是本机 subprocess 替身，不称作真实 SSH 跨机恢复。 |

非作者已审查完整 `94c59e5`→`94ee7cd` 与方案→实现增量，代码/简洁性及上述本机
回执 PASS；实际 Windows 运行结论单独等待，不能由此代替。

便携 Windows fixture 使用 fake OS/key/process，不是 Windows 运行证据；`ssh -G`
只验证真实配置解析。路径回归在实际存在的 public identity 与 known_hosts 的受控
cwd 内解析，并另外核对 Popen 的原 socket 环境和父 cwd；不称其证明了认证。

## CI 与剩余边界

默认 PR 保留 portable Windows process/pipe 和 installed-core 两个产品 job；加入
上述凭据与 argv 回归。独立 `authentication-candidate` 仅 workflow_dispatch；其
Stage B normal/wrong-pin 已有产品检查，AGAIN/N 专有协议没有移入生产。Stage A
仍可按原 probe CLI 手动运行；hard-controller-kill/foreign-client 历史证据并不成为
当前产品新增覆盖。原安装路径、wrong-pin 零释放、原取消、expiry/revoke、原进程及
helper 停止 oracle 没有删减。

整改后真实 Windows installed-wheel 与最终 fast/full 待各自精确回执。
Windows→真实 Linux 的 submit/recovery/cancel 继续 BLOCKED：没有
授权外部 endpoint，Windows ForceCommand 不是 Linux helper。真实 GPU、模型、IdP
或部署未纳入本次验证。主代理最终确认及本次回执文档增量审查仍待完成。
