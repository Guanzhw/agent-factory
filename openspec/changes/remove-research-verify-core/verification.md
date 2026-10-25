# Verification

基线 main `a2e021c97ba2257d86c1ec484296bbeda0b6c05a`；原七 PR 已合并，主线 CI40164609318 成功。本变更仅获独立 Draft 授权，不合并或部署。

环境：4 CPU /16 GiB；Python3.12.14、uv0.12.19、Node24.19.0，锁定依赖，无付费/真实模型调用。新临时 PostgreSQL17.11 仅监听 loopback55439。用户05:40UTC确认旧数据精确清单后，复核并删除5文件、52空目录、唯一旧停止容器/卷，逐项不存在核验成功；新验收DB、源码/Git/证据/OPENCODE_GO 均保留。

原始日志与命令/UTC/耗时/退出码：`/workspace/scratch/core-only-20261025/`。仓库内将补充安全汇总与截图，避免仅本地路径交付。

## Completed checks

- Web完整检查：lint/typecheck、431测试、build成功；随后中性F标志的小改通过9项针对回归，最终重建/浏览器截图已完成。
- Python完整发现/fast选择器：1812发现、333 Python/48 PG选择、1431仅full；这是collection而非执行。完整required首次发现2条残留选择器，在执行前失败；删除应用专属SSHPrerequisite类选择器并指向改名后的通用stop-proof用例。
- Python架构402模块、0违规、0覆盖缺口；Python/JS checker各11测试通过。JS首次空apps拒绝已修正为允许零应用、继续要求非空core和装配方向，新增回归通过。
- 独立core wheel：12.232秒，exit0；无应用包、初始0表、空应用/材料、成员资源和账号管理可用，真实native启动/health/干净关闭，Research路由/表不存在；没有模型调用。
- 远程portable30通过（含5个退役placement保护）；纯同步治理/生命周期/policy18通过。
- 原生/模型36项首次35通过1失败：旧环境限额测试仍用已移除夹具；现改为真正BoundedProcessAdapter、kernel RLIMIT、valid stop、UNKNOWN不重派，针对1项通过。完整PG整合验收正在运行。
- 沙箱中的native portable等待已终止留trace；同一checksum case在获准环境1.953秒完成，没有改产品超时。npm install首次沙箱EPERM保留，获准子进程安装成功。
- 浏览器首次demo桌面/移动完成；production-local夹具旧managed-role API失败。改为现有TrustedTeamProvider需要的活跃目录成员，第二轮36.882秒完整通过demo和production-local桌面/移动：真实HTTPS与业务API，登录、空catalog/tasks、资源、退出重登、直达刷新、旧URL。身份是本地合成OIDC，不是外部生产身份。
- npm生产与完整audit各exit0、0漏洞。
- 独立review发现空目录工具默认literature_search导致保存异常，已删除虚构内建建议、保持字符串权限、空提交拒绝并新增回归；review复核无剩余确定阻塞。其静态结论不替代运行验收。

## Pending

最终完整core PostgreSQL、最后截图、最终源码静态/精确CI、临时资源清理。历史MCP时序失败不能因本次移除或单例通过而宣称解决；不宣称整套加速或真实生产身份/外部模型验收。

## Browser artifacts

最终浏览器运行70.684秒exit0；两个新空数据库、两种身份模式、每种桌面/移动均通过。以下截图使用 production-local 合成OIDC，不是外部真实组织账号；登录页图取自已完成退出、会话已核验失效后的状态。

- [结构化结果](evidence/browser.json)
- [退出后的登录页](evidence/desktop-logged-out-login.png)
- [空应用主页](evidence/desktop-home.png)
- [移动资源入口](evidence/mobile-resources.png)
- [移动退出状态](evidence/mobile-logout.png)

完整PG第一轮仅collection失败，未执行测试；第二轮发现共享operation材料未显式binding及预检缺失，另有setup错误后未注册cleanup。为避免继续受残留worker影响，于405.906秒SIGINT结束（exit-2，绝非通过）；保存逐项失败、进程线程等待点、26线程/676692kBRSS，以及KeyboardInterrupt栈，确认精确进程消失且无子进程。当前先针对修复路径验证，再进行最终全量；不能据此宣称稳定性已完成。

## Go queue ownership correction

针对性81项运行279.545秒保留5个失败记录（远程批准/拒绝两subtest、Go三项）。Go原有“失败后不允许队列扩大provider尝试”保护实际藏在旧ResearchDelegatingModel。删除应用后，默认Go配置的队列2次会把UNKNOWN与HTTP调用翻倍，这是实际职责耦合，不能只给测试开启validation开关掩盖。

现由deployment的native_queue_attempts对opencode-go配置恒定选择1次原生job（模型内部有界retry不变），core直接装配也在目录/DB创建前拒绝非精确int1；Go预检本来就要求显式opencode-go配置。默认validation=False的三个真实PG/local HTTP合成provider回归通过，原HTTP/usage/UNKNOWN断言保留并新增job attempt/max_attempts断言。独立复核确认直接core绕过路径封闭。

限制：不追溯修改旧job行的max_attempts，也不迁移其他环境的历史任务；本环境旧数据按用户清单另行删除。此处没有真实供应商、余额、订阅费用或付费调用验收。

远程批准首次403来自未声明的fixture_operation；改为真实bounded-process-v1与精确scope后409来自两端独立发布应用的createdAt导致不同digest。接收端现通过真实snapshot import复用origin精确版本，不mock校验或扩大生产allowlist。单用例（含批准/拒绝）18.576秒通过，整class5项57.924秒通过，正常关闭全部worker/scheduler。

最终源码冻结前：所有已知迁移失败均有针对性修复/通过证据；将对这一修复集合执行完整core PG和精确提交CI，当前尚未宣称全量通过。

## First frozen full verification (a79ffc0)

[PR104](https://github.com/Guanzhw/agent-factory/pull/104) 保持 Draft。精确提交 `a79ffc0870a5db94808a4c2fc287e39e25c3acb6` 的 [fast CI40168238226](https://github.com/Guanzhw/agent-factory/actions/runs/40168238226) 通过；[full CI40168529122](https://github.com/Guanzhw/agent-factory/actions/runs/40168529122) 失败，不能宣称全量通过。

- 本地完整 PG：1815 tests，2303.599秒（含包装2319.448秒），failures=14/errors=6/skipped=5，exit1。失败数包含subtest，不等于失败用例ID数。required五组中四组全通过；owner_byok_default_off为101/102，长路径broker夹具错误。
- 完整CI：Windows 1815项，201.665秒，errors=2/skipped=736；PG 1815项，1194.436秒，failures=11/errors=5/skipped=5。两平台前端与Linux Python静态检查通过。
- 以上是不同运行环境的结果，不能把耗时差或测试移除数量作为整套提速证据。CI控制台最终输出缺少部分traceback，新增固定版本官方artifact步骤只保存完整PG日志7天，仍传播原测试退出状态。

已确认迁移缺陷及修复对应：Go Settings重复关键字、Luna旧fixture入口/peer；remote模型provider与定价标识不一致、定价变更误触zero-local条目；模板仍期望Research产物；broker测试transport丢失长路径目录FD连接；测试残留已删除科学合同。保持模型/usage/ledger、材料hash、权限撤回、真实原操作身份断言。未知合同拒绝断言迁至通用policy测试，未随科学合同测试删除。

未闭合的时序问题：MCP撤回测试在撤回前启动屏障超时；MCP容量测试第二次调用在DELETE授权总期限内未完成；可复用MCP第二账号任务在派发前授权读取耗时；remote断读测试尚未launch就遇origin authority通信不可达。不能把UNKNOWN当已释放、把native completed当清理完成，或提高期限掩盖问题。原始日志与精简分析均保留。

有界诊断：MCP单例1项1.422秒、相邻两例加目标3项4.753秒均通过，原2秒断言不变；只补pending的finally cancel/gather，避免失败后遗漏任务异常。诊断runner首次因重复注入已应用的清理代码产生IndentationError（未执行case），修正runner后才得到上述结果。容量单例一次通过（包装30.237秒），保留采样未见PG锁/池耗尽；事件环仅保留末段且未覆盖pre-ping，不足以关闭原慢回调原因。独立review确认候选未弱化断言或生产授权，但不是执行验收。


Remote有界诊断一次：77.729秒测试/82.780秒包装，exit1。原full在无lease阶段出现ORIGIN_AUTHORITY_UNAVAILABLE；本次30次origin授权均200、无HTTPError，进入allocation剩4.812秒，五次before_effect累计4.789秒，最后越过原5秒期限，最终never-dispatched/allStopped并回收。没有进入read-disconnect目标阶段，故不算该场景通过。510条同步trace约57.6KB可能扰动临界时序，尚未量化；未调整生产期限、未重置lease、未重试追绿。


迁移修复针对性32项：226.769秒（包装231.129秒），全部通过、零跳过、exit0；包含两个Go模型、Luna512输出上限、六类材料发布/原生产物hash、长路径broker、未知合同拒绝、真实TCP远程进程与远程计费/恢复。完整源码变更仍须最终精确CI验收。命令/UTC/退出码见[结构化运行证据](evidence/verification-runs.json)。


可复用MCP多账号单例聚合诊断一次通过，内部66.570秒（包装75.113秒），377 callbacks、53186观测事件；完整pool connect（含pre-ping）、SQL与固定函数类别聚合，避免早期环形日志丢失。保留原期限和全部断言；本次通过不关闭完整运行慢因。未进行生产授权优化或重复全量追绿。

最终修复静态：Ruff通过、Pyright 0 errors（16.055秒）、CI scope/summary9项通过、diff whitespace通过。[MCP安全聚合摘要](evidence/reusable-mcp-diagnostic.json)保留完整统计；pool connect最大38.811ms、SQL最大173.510ms、callback最大643.884ms，未复现完整运行慢因。
