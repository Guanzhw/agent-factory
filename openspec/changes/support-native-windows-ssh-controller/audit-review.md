# SSH1/2/3、POSIX 路径与 Q1 独立审查

Reviewer: `audit_quality`，非方案/实施作者。审查记录独立维护，不修改产品源码。

## 方案审查 — 2026-10-26

精确范围：`94c59e5954f5acacb039a73fa3332381fd542fe2` → `036c6087f112b0c399677c9a39a9be95b2dcf844`，`/workspace/agent-factory`，4 个既有 change artifact，+57/-1 行；无代码变化。

**方案 PASS，允许按已限定范围实施；不代表实现、Windows 或真实远端验收 PASS。**

- SSH1 使用同一 `min(caller deadline, lease expiry)`，取消独立六秒总期限；固定 helper 只接收非秘密 deadline 元数据并拒绝非有限/过期值。授权、取消、一次释放和原 scope 均保留，不增 retry。需要同时验证慢 guard/慢 helper 与真正期限到达，不能通过刷新期限解决。
- SSH2 只区分原 process/broker/pipe/kill 未确认与“这些已确认结束但密文目录删除失败”。后者仍报告失败、清除密码、占有界 slot，但不故障扩散至所有 owner；前者仍关闭新 admission。有限 retained slot、显式 close 报错、不自动重扫的范围与现有责任相称，不引入恢复服务。
- SSH3 小固定 argv helper 共用真正相同的 pin、proxy/forward/config/control 与 endpoint 参数；平台保留不同凭据/进程语义，不把两种 manager 强行合并。POSIX child cwd 固定文件和显式 IdentityAgent 环境引用可避免 `-o` 对绝对路径空格/引号的二次解析；原 lease socket 只写入该 child 环境，禁止继承外部 agent/config，父 cwd 不变。
- Q1 把独立候选 Stage B 变为按需，仍默认执行真实 portable 与 installed-core。normal/wrong-pin 的产品 oracle 保留；探针专有 AGAIN/N 不迁。历史 Stage A hard-controller-kill/foreign-client 保持手动诊断边界，不声称产品新增覆盖，也不为删除重复 job 新建一套矩阵。
- 保留旧失败/旧 PASS 的精确归属及 POSIX 缺陷早于 PR104 的事实；Windows→真实 Linux 原任务恢复仍有独立验收边界，不能被本次 portable fixture 代替。

验证提醒（已通知作者）：`ssh -G` 对不存在的 `-i identity.pub` 会忽略该文件并输出默认 identities；路径用例应创建存在的合成公钥文件、在原 child cwd 解析并断言唯一所选 identity。`-G` 输出 `IdentityAgent SSH_AUTH_SOCK` 只证明选项被接受，实际 lease socket 仍需 child env/transport seam 核对。此次审查仅运行无网络的参数解析，没有调用真实 SSH host 或使用凭据。

实现 gate：收到具体 SHA 后审 base→head 全部产品、测试、CI、文档 diff，并复查原 host key/owner/secret/process/UNKNOWN 断言。重型 PG、浏览器与 Windows CI 由 root 协调，未运行不得标 PASS。

## 实现审查 — 2026-10-26

精确完整范围：`94c59e5954f5acacb039a73fa3332381fd542fe2` → `94ee7cd1587fd3d63926f0495832b6e25921540f`，13文件 +343/-38；同时审阅先行方案 `036c6087f112b0c399677c9a39a9be95b2dcf844` → 该head的实现增量。

**代码、简洁性及已读取本机目标验收 PASS，无源码整改阻断。整改后的实际 Windows installed-wheel/portable CI 未运行，仍是独立待验门槛；此结论不宣称完整发布验收。**

- Deadline修复没有延长调用预算：manager仍取caller/lease最小值，broker固定connect/READY/释放/RECEIVED与helper都使用原值；最后guard、cancel及释放前deadline检查保留。helper的有限/过期元数据校验局限于此边界，没有备用密码或retry路线。[Python3.12官方monotonic说明](https://docs.python.org/3.12/library/time.html#time.monotonic)支持同机进程共享该时钟；这不替代真实Windows运行。
- cleanup仅增加局部阶段布尔值：process.close、broker退出、pipe/kill错误确认后才把失败限于目录残留；目录失败仍抛SSHExchangeCleanupError、清零密码、保留failed slot。原carrier.failed及真实进程/broker/pipe不确定仍关闭manager；显式close仍不伪报成功。未增registry、后台清扫、重试或无界残留。
- `ssh_command.py`只有15行固定组装，平台凭据参数保持分离。POSIX使用固定child cwd/public identity/known_hosts及仅该lease的SSH_AUTH_SOCK；Windows仍IdentityAgent=none、AddKeysToAgent=no及一次密码prompt。原host pin、禁proxy/config/control/agent forwarding及endpoint尾部保持，没有新增授权allowlist。
- 实际解析回归先通过原pinned_ssh创建存在文件，再在捕获的child cwd调用ssh -G；断言固定identity且无默认key、严格pin及精确child env/父cwd，避免缺失-i产生假通过。更新旧personal SSH断言是表示方式从argv转为显式env，原选中socket证明仍在。
- Q1默认PR跳过候选probe，仅按workflow_dispatch运行；portable lane加入真正产品凭据/argv回归，原installed-core与Windows process测试源码无diff。StageA历史场景、probe专有AGAIN/N与实际产品覆盖边界均未混写。
- 已读基线产品加新增测试的原始 `ssh-corrections-before.log`：16tests、11失败subcases；修后 `ssh-corrections-unit.log`：94/94、0skip、4.489s。首次修后28项的1个ERROR只有作者工具回执摘录，见 `ssh-corrections-check-evidence.md`，不能称完整原始日志；所述fixture提前离开scope触发取消与现有源码相符，修正只等待原broker完成，未改产品deadline/取消/失败oracle。
- 已读精确94ee7cd的 `ssh-corrections-real.log` / `ssh-corrections-real-result.json`：5/5、0skip、17.765s；含三项真实个人SSH、实际安装core wheel/非22端口映射loopback及原controller硬杀native用例。最后一项SSH transport是本地subprocess替身，PG/native真实，不能当Windows→Linux网络恢复证明。新增数据库、存活owned进程和fixture目录残留均为空。
- 静态原工具回执摘录给出全树Ruff PASS、Pyright0errors/14个Linux本机Windows模块source warnings、architecture518/0/0；环境.venv提示保留。完整diff whitespace本次独立通过。未为补日志重跑成功套件，也未自行占用PGslot。

必要边界仍保留：当前owner/vault/连接授权、host key、原进程/helper持有者、一次秘密释放、失去回执的原任务UNKNOWN与零替代dispatch。没有将SSH本地进程结束等同远端任务停止。实际Windows整改后执行、Windows→授权真实Linux原submit/recovery/cancel、GPU/model/IdP、最终fast/full与部署均未由本轮Linux证据关闭。

后续作者仅补本次Linux回执与原样独立review时，应核对精确文档增量和源码无变化；不反复写入“审查审查”的新记录。

## Full 导入修正方案审查 — 2026-10-26

精确范围：`6e15459484ce3ef4a63b22426b43a8891a310512` → `1dfc4b091bd2d189ca76c090d1b04b11e839bc74`，4 个既有 artifact、+27 行；产品与测试未改。非作者 `audit_quality` 已读完整方案 diff、support 模块、实际 carrier 平台选择和两个原导入断言；独立 OpenSpec strict 与 diff-check PASS。

**方案 PASS，可先在精确 spec head 复现原两项失败，再实施；不代表实现或新 full 验收通过。** 原 full `40272188443` 完成 2261 项，2 failures、0 errors、15 skips、`accepted=false`；六组 required 全通过不能抵消普通失败，原始失败继续保留。

- 仅以 `sys.platform == 'win32'` 包住原 8 个 Windows API 导入，符合既有 `personal_ssh` 的 carrier 平台选择。support 顶层无须调用这些 API；非 Windows 导入成功不承诺执行 Windows primitives。无需 loader、代理对象、异常吞噬或逐函数兜底；Windows 缺失依赖仍直接失败。
- 保留原 source/独立 wheel 全模块 walker、模块集合、全部断言和依赖 marker；不通过排除模块、Linux 安装 pywin32 或放宽断言取得通过。host key、owner/原身份、秘密释放、holder/Job、期限、取消及清理函数逻辑不变。
- 实现后复审完整 `62614177` → 新 head 和本修正增量，读取相同两项首失败/修后及相关 portable/static 回执；新 head Windows 专项与新组合 full 由根核验。旧 full 不重跑追绿，真实远端/GPU/model/IdP 边界不由导入测试关闭。

## Full 导入修正完整实现复审 — 2026-10-26

非作者 `audit_quality` 审查完整 `62614177c23c4d2cd0caf6b7c91418e74fde8ad4` → `27841560acff3b505bc28feefb8b6d25623e01b0`（54 files、+4219/-75），以及修正基线 `6e15459484ce3ef4a63b22426b43a8891a310512` → 同 head（6 files、+54/-10）。产品 checkpoint 为 `9600f9ca0d3c0098e6ba6e3e68995ec90e72177e`；其后仅 `verification-audit.md +16`。另由非作者 `ssh_fixture_crosscheck` 只读补核全部测试、CI、历史 probe 与文档，本结论整合双方当前 diff 审查，不沿用旧 PASS 替代。

**完整源码/简洁性与本机目标验收 PASS，未发现需继续修改源码的阻断；新 head 的真实 Windows 专项与新组合 full 仍待，不能据此解除合并/部署暂停。**

- 本修正唯一产品路径为 `windows_ssh_support.py`：原八项 Windows API 导入加平台条件与标准 `TYPE_CHECKING`。所有 class/function AST 相对 `6e154594` 完全相同；`TYPE_CHECKING` 运行值为 false，只提供静态可见性，无 ignore、替代对象、异常吞噬、loader 或逐函数 guard。Windows 仍加载原 API，缺依赖仍失败；非 Windows 可导入不表示支持执行 Windows primitives。
- 两个原 source/独立 wheel walker、模块集合与断言完全未改，未排除任何 Windows 模块。检查者以显式当前源码路径独立运行同两项：**2 PASS / 4.280s / 0 skip**；wheel 由原测试现场构建，未使用 PostgreSQL，结束后临时 distribution 根为空。原输出保留在外部 `ssh-core-import-correction/independent-targeted.log`。
- 已读作者原始证据：spec `1dfc4b0` 两 FAIL / 4.407s；首次 `199dec7` 两 PASS / 4.222s、57 portable PASS，随后 Pyright 61 errors / 6 warnings；最终 `9600f9c` 原两项与同 57 portable 共 59 PASS / 8.511s / 0 skip，Pyright 0 errors / 14 Windows 模块源码 warnings。首次静态失败未隐藏；当前 source 的显式配置、Linux 无 pywintypes/无 Windows API 加载记录与修正一致。Ruff、架构 518/0/0 回执通过；最终 OpenSpec strict 与完整 diff-check 另经本审查者通过。
- 完整产品 diff 保留当前 owner/vault/lease 与原任务身份、严格 host pin、禁止外部 SSH config/proxy/agent forwarding、原 UNKNOWN 与取消语义。Windows 仍为加密临时私钥、一次 passphrase、原 helper/client/parent 身份和 Job/holder 清理；共享 deadline 不刷新预算，密文目录删除失败仍报错并保留有限 slot，进程/broker/pipe 不确定仍关闭 admission。固定 argv 的共用与 POSIX child cwd/SSH_AUTH_SOCK 路径修正职责明确，未增加恢复框架或额外授权规则。
- 完整测试 diff 的 contextmanager/deadline 适配保留原取消等待、单次发送、进程数量及错误传播。独立 exchange 原回收断言未动，实际 Windows 回归在 scope close 前检查回收；未发现改 oracle、放宽期限或增加 skip。主 CI、全量 discovery 与 required selectors 不变；本次增量没有改任何 tests/CI/依赖。全 PR lock 仅增加原 Windows 加密所需 bcrypt 5.0.0 和对应项目依赖，其他锁定包未升级。
- Q1 candidate 仍仅手动，默认保留不空且零 skip 的 portable contracts 与真正 checkout 外安装 core wheel 的两个产品消费者验收。原 wrong-pin 零释放、取消不替换、expiry/revoke 零新进程、held handles 与清理 oracle 保留；历史 Stage A/Stage B 不是产品新 head 证据。旧文档中的 `445a2ce` 均只能按其精确历史 SHA 解读，当前导入修正及未验范围以 `verification-audit.md` 新节为准，不复制历史报告。

`full40272188443` 的完整失败日志与 `accepted=false` 保留；required 六组通过不抵消两项普通失败。本次没有运行新的真实 Windows、组合 full、浏览器或外部资源；旧 Windows success 与本机绿色结果不得替代新 head 验收。Windows→授权真实 Linux 原 submit/recovery/cancel、GPU/model/生产 IdP 与部署边界继续未验。主代理核对最终文档增量与后续真实 CI 后管理任务状态，本审查未勾 checkbox、发布、合并或重跑旧 full。
