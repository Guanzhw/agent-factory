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

## Full acceptance import correction (2026-10-26)

最终组合 [full40272188443](https://github.com/Guanzhw/agent-factory/actions/runs/40272188443) 测试 head `9c392a4d9c15b8b4ec61047e266857b01f45833a`、tree `92e125156e929c3091d18f4d43669d811749f489`：2261 项 / 1860.584 秒，2 failures / 0 errors / 15 skips，`accepted=false`。六个 required 组全部通过不能抵消 source 与独立 wheel 全模块导入的两项普通失败。原 artifact 已独立校验并保存在 `/workspace/audit-remediation/full-40272188443-independent-pg.log`；本段不把旧 full 改为通过。

原因是 `windows_ssh_support.py` 顶层导入 `pywintypes`；该块来自 PR138 原实现 `9bf89776`，在 `94c59e5` 已存在，与后续 deadline/cleanup 修正无关。修正基线 `6e154594`，非作者方案 PASS 的 spec head `1dfc4b091bd2d189ca76c090d1b04b11e839bc74`。产品仅给原八项 Windows API 导入加 `sys.platform == 'win32' or TYPE_CHECKING` 条件；函数体、两条原测试的 walker/断言、依赖 marker 和 CI 均未改变。非 Windows runtime 不导入 API；Windows 缺依赖仍正常失败，无替代实现。

| 精确修正阶段 | 本地结果 | 外部原始证据 |
| --- | --- | --- |
| spec `1dfc4b0`，产品仍为基线 | 原 source/wheel 两断言均 FAIL，4.407 秒，均为 `ModuleNotFoundError: pywintypes` | `before.log` |
| 首次实现 `199dec7` | 同两项 PASS，4.222 秒；57 项 portable PASS，4.675 秒；Pyright 静态裁掉 Windows 条件后报 61 errors / 6 warnings | `after.log`、`portable.log`、`pyright.log` |
| 最终产品 `9600f9ca0d3c0098e6ba6e3e68995ec90e72177e` | 类型可见性补充后，原两项加相同 57 portable 共 59 PASS / 8.511 秒 / 0 skip；Ruff PASS，Pyright 0 errors / 14 Windows 模块源码不可用 warnings，架构 518 modules / 0 violations / 0 gaps，OpenSpec strict 与 diff-check PASS | `final-targeted.log`、`*-final.log` |

本次外部证据统一位于 `/workspace/cross-pr-audit/ssh-core-import-correction/`，未把原日志入库。命令使用现有 Python 3.12.14 venv 和显式当前源码 `PYTHONPATH`；`environment.json` 记录产品/测试 `__file__` 属于本 tree、Linux 未安装 `pywintypes` 且未加载任何 Windows API 模块。Pyright 配置显式当前源码 `include/extraPaths` 与共享 interpreter，未借用旧 editable 产品代码。

最终测试选择为原 `test_core_package_distribution.CorePackageDistributionTests.test_all_installed_core_modules_import_with_application_packages_absent`、`test_core_runtime_boundaries.CoreRuntimeBoundaryTests.test_core_imports_without_loading_any_research_package`，加 `test_windows_ssh_credentials test_ssh_command test_ssh_exchange test_personal_ssh.PersonalSSHTests`。本次无 PostgreSQL、浏览器或新的真实 Windows 运行；不重复旧组合 full。最终完整 PR138/增量非作者复审、新 Windows 专项与新组合 full 由主代理分别核验，旧 Windows/本地绿色结果不替代新 head 验收。
