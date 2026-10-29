# Design

## Context

动机和精确允许文件见 [proposal.md](proposal.md)。基线已有 `session_tools._directory` 的 POSIX `dir_fd/O_NOFOLLOW`、`_read_opened` 单硬链接检查、`_edit` 精确替换，以及 `_personal_cli_process` 的权限检查/预算/取消/UNKNOWN 契约。Windows 当前在构造阶段被拒绝。

`WindowsSSHProcess` 已实现 `CreateProcessW(CREATE_SUSPENDED)` → Job 归属 → `resume`，拥有 `KILL_ON_JOB_CLOSE`、明确句柄继承列表和 cwd。实际缺口是 stderr 丢弃、普通 CLI 尚未接入，以及现有 `close()` 只等待根进程，不能证明 Job 内全部进程停止。`ssh_exchange` 已使用 Python 3.12 支持的非阻塞管道。

## Goals / Non-Goals

**Goals:** 先用现有 Agno 工具完成一个本地代码修复；再以原生 Windows 句柄证据验证取消和原操作重启。保留 POSIX 原实现与公共结果，不改变队列或效果状态机。

**Non-Goals:** 不抽象通用环境/文件系统/执行框架，不迁移框架或数据，不把受信任 OS 用户运行包装成沙箱；其余非目标见 proposal。

## Decisions

1. **文件适配留在 Research。** 保留 POSIX 描述符遍历；Windows 采用现有 pywin32 的 `CreateFile`，从卷根逐级打开目录，使用 `FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS` 并按句柄检查属性。保留整个祖先句柄链到文件操作/cwd 使用结束，目录不共享 delete/write，防止重命名或转成 junction 后再按路径打开。最终文件用不跟随 reparse 的句柄打开，检查普通文件、非 reparse、单硬链接后才读写；新建用 `CREATE_NEW`，已有文件不预先 truncate。句柄生命周期由上下文管理，不采用 `resolve()/lstat()` 后普通 `open()` 的检查/使用分离。只提取读、搜索、编辑实际共用的私有薄函数；不建协议类体系。
2. **路径语义保持工具协议。** 工具继续使用 `/` 相对路径；Windows 分支拒绝冒号/备用流、驱动器与 UNC、保留设备名、尾点/尾空格及系统非法字符，避免命名别名。显式根须为已有绝对目录，祖先同样拒绝 reparse；不静默创建部署根。owner/session 哈希目录照旧，命令 cwd 持有相同目录保护直到进程接管。
3. **复用唯一 Windows 进程所有者。** 为 `WindowsSSHProcess` 增加可选 stderr 捕获，普通 CLI 开启，旧 SSH 默认仍为 devnull，避免未读取的第三条管道阻塞旧协议。Windows CLI 创建流程保留异步 `before_spawn` 和权限复核，挂起创建/归 Job 后再检查取消与权限、最后 `resume`；如创建放入工作线程以保持事件循环响应，取消必须 shield 并接回返回的原所有者，不能遗弃线程结果。
4. **管道不使用阻塞读写工作线程。** 复用 `ssh_exchange` 的具体模式而不改它：`os.set_blocking(False)`、小块 `os.read/os.write`，在单 async 循环推进三流、检查权限/截止时间/总输出预算并让出事件循环。根退出后先停止 Job 内剩余进程，再有限排空和关闭三流；不是等 EOF 才发现根退出。普通 stdin 提前关闭和 broken pipe 按已有 CLI 语义处理。
5. **从原 Job 证明停止。** 在 Job 句柄仍由原对象持有时调用 `TerminateJobObject`，查询 `JobObjectBasicAccountingInformation.ActiveProcesses`，只有零活动进程且根进程回收和管道收尾确认后才 `stopped=True`。重复停止使用同一所有者；失败/超时为 UNKNOWN。`KILL_ON_JOB_CLOSE` 是服务硬退出后的兜底清理，不是完成回执或无副作用证据；不按 PID 重新拼树，也不把普通 Job wait 信号当全部退出。
6. **保持明确环境与现有持久化。** Windows 只补普通解释器启动实际需要的 `SystemRoot`、调用私有临时目录变量，以及有明确消费者的 UTF-8 设置；PATH 继续来自配置，不复制 `os.environ`。Windows 的 `os.defpath` 含当前目录，不放宽原绝对目录配置要求；说明使用明确的解释器/工具目录列表，并验证命令查找不会隐式选择 cwd 中的同名程序。只直接执行普通程序，不自动通过 shell 启动 `.cmd/.bat`。`effect_reserve/complete`、owner/session guard、`_model_boundary` 和 public result 不改；恢复场景通过现有入口测试。

## Risks / Trade-offs

- Windows 目录共享模式与 reparse 替换竞态必须真实验 → 在临时目录测试根/祖先/文件 junction、硬链接、打开期间改名/替换及清理后释放句柄；如句柄方案不能满足边界，先更新设计并独审，不能降级为纯路径检查。
- 中文路径可独立于控制台编码正常工作，CLI 字节输出仍取决于程序 → 文件统一 UTF-8；普通 Python 场景用明确 UTF-8 设置并测试，不猜所有 CLI 都输出 UTF-8。
- Windows SSH 是已有消费者 → stderr 默认和原构造/关闭调用兼容，运行原 Windows SSH 回归。
- 云端 Linux 不能证明 Windows 系统调用 → 协议 mock 明确标记；真实 Windows 的红→绿、整树停止和隔离 PG 重启另记结果。无实机证据不标该能力已验收。

## Migration Plan

无数据库迁移或新持久配置。非作者先审核本规范精确提交，再实施；云端完成静态/边界和 Linux 相关回归后交本地线程在授权临时环境验证。发布、正式登录配置、凭据和 TLS 由协调线程另行处理，本变更不执行。

## References

- [Microsoft CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)：共享模式、目录句柄、reparse 与独占新建。
- [Microsoft 文件命名](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file) 与 [句柄属性](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandle)：Windows 路径别名与最终对象校验。
- [Python 3.12 os.set_blocking](https://docs.python.org/3.12/library/os.html#os.set_blocking) 与 [subprocess 环境](https://docs.python.org/3.12/library/subprocess.html#subprocess.Popen)：Windows 管道与 SystemRoot 要求。
- [Microsoft Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) 与 [Job accounting](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information)：原 Job 生命周期与活动进程计数。
- [pywin32 b312 win32job](https://github.com/mhammond/pywin32/blob/b312/win32/src/win32job.i)：锁定版本的查询接口；实施前同样核对所用 win32file 接口。
