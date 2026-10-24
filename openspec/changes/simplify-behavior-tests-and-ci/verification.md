# Verification

状态：代码验收与独立审查完成。合入及主线状态以 [PR96](https://github.com/Guanzhw/agent-factory/pull/96) 的提交/检查记录为准。

基线为 `3e206920b8ea86598fca35d3cedcd80dfbdf160d`，完整 CI：[40078129086](https://github.com/Guanzhw/agent-factory/actions/runs/40078129086)。此前 PR95 的 fast 和本地完整数据仅作历史参考，本次比较使用新的基线及最终运行。

## Before

- Linux 普通完整执行：3201 项，2620 成功、581 跳过、零失败/错误；执行 205.837 秒，job 244 秒。
- Windows 普通完整执行：3201 项，1978 成功、1221 跳过、1 失败、1 错误；执行 217.033 秒，job 316 秒。两个失败分别为隔离依赖缺失 pywintypes 和真实 MCP 调用的 UNKNOWN，均保留原始日志。
- Web：两种系统均 61 文件、699 项通过；Ubuntu job 37 秒、Windows job 77 秒。npm cache 分别命中/未命中，不能将差异归因于代码。
- Linux 完整 PostgreSQL：3201 项，3135 成功、66 显式跳过、零失败/错误；执行 2449.930 秒，完整执行 step 2474 秒、job 2534 秒。七组 required 均实际通过：130/130、33/33、9/9、11/11、10/10、19/19、6/6，各组 `notPassed=[]`，`accepted=true`；独立核心安装/启动/干净关闭通过，step 11 秒。
- 基线完整 CI 最终为 failure（Windows 夹具失败，汇总据实失败）。七个 job 合计 3217 秒，即 53.617 原始 job 分钟；这不是账单分钟。旧 PG workflow 只打印进度尾部和末 400 行，仅留下 316 个唯一成功 ID，不能虚构完整基线 PG ID 清单。

## Final integration and comparison

最终代码 `13f36d25fe4c7552c507875dab4a75d566c438ab` 的 [完整 CI 40079197408](https://github.com/Guanzhw/agent-factory/actions/runs/40079197408) 和 [fast CI 40079170515](https://github.com/Guanzhw/agent-factory/actions/runs/40079170515) 均 success。后续提交仅更新验收文档；工作流、依赖与测试代码保持该已验证版本。完整分阶段测量、环境和 ID 对照见 [CI comparison](ci-comparison.md)。

| 完整 CI 观察项 | 清理前 | 清理后 |
| --- | --- | --- |
| Linux 普通 Python | 3201 项：2620 成功、581 跳过；job 244 秒 | 行为执行并入 PG；保留静态/架构 job，40 秒 |
| Linux PostgreSQL | 3201 项：3135 成功、66 跳过 | 3198 项：3132 成功、66 跳过 |
| PG unittest 执行 / 完整 step / job | 2449.930 / 2474 / 2534 秒 | 2349.101 / 2372 / 2408 秒 |
| Windows Python | 1978 成功、1221 跳过、1 失败、1 错误；217.033 秒执行、316 秒 job | 1977 成功、1221 跳过、零失败/错误；198.652 秒执行、271 秒 job |
| Ubuntu Web | 699 项；Vitest 12.88 秒、job 37 秒 | 695 项；Vitest 16.75 秒、job 79 秒 |
| Windows Web | 699 项；Vitest 21.39 秒、job 77 秒 | 695 项；Vitest 16.32 秒、job 69 秒 |
| 七个 job 合计 | 3217 秒 / 53.617 原始 job 分钟 | 2876 秒 / 47.933 原始 job 分钟 |
| workflow 开始至最后 summary 完成 | 42 分 33 秒，failure | 40 分 27 秒，success |

七组 required 的数量与结果均保持 130/130、33/33、9/9、11/11、10/10、19/19、6/6，全部 `notPassed=[]`；独立核心真安装/启动/干净关闭通过。组间可重叠，不能把这些数字相加当作唯一用例数。

基线 Linux 普通测试有 2620 个实际成功 ID。扣除明列的 7 个诊断矩阵删除项，**2613 个保留 ID 在最终 PG 中全部实际成功**，没有缺失或改为跳过；4 个新增 ID 也全部成功。最终 PG 完整日志的 3198 个唯一 ID 与 runner 汇总一致。失败文献检索进入 PostgreSQL provenance 的用例实际通过；未发现数据库缺席时独有而被遗漏的普通行为分支。

此次确定减少了一个 Linux 全量发现/行为执行入口。总 job 用时观察值减少 341 秒；PG 主耗时下降 100.829 秒属于单次独立 runner 观察，不能归因于本次少量断言调整或承诺为稳定收益。Ubuntu 前端增加锁定浏览器安装 20 秒、两场景 smoke 7 秒、官方审计约 1 秒；保留这项新增覆盖。基线 Ubuntu npm cache 命中、Windows 未命中，最终两者均未命中；uv 设置/缓存阶段也有差异。两版本使用同类 GitHub hosted runner，Linux/Windows Node 分别为 24.21.0/24.22.1；这不是同一物理机器上的因果性能实验，也不是账单金额比较。

## Behavior coverage and focused checks

- 五个 Python 候选模块同一 Windows CPython 3.14.3：37 项（36 成功、1 Docker opt-in 跳过）变为 34 项（33 成功、同一跳过）。删除 7 项人工 hostile-object/诊断镜像矩阵，新增非法 transport、真实退出码、未分类错误脱敏和公共并发顺序共 4 项；有限 schema、错误码/退出码、凭据脱敏及 provenance 保留。单次执行 4.648→4.420 秒，不宣称稳定速度提升。
- Node 24 完整 lint、TypeScript、构建通过，60 文件、695 项通过。删除 3 项浅层源码扫描及 5 项序列化检查，新增 4 项挂载 DOM 行为；另将唯一 glob 规则移入 AST checker，checker 由 9 项变为 10 项。新任务入口、历史折叠、默认可见字段、外部文本、原请求恢复及精确 API 次数均保留。目标前端集三次新进程中位数为 6.282→6.328 秒；改善的是断言价值与抗结构变化能力，此处没有速度提升。
- 原 PubMed 测试漏过“先请求后拒绝”的反例，连接 transport 后捕获；公共检索测试捕获共享锁被绕过。前端 class/属性顺序改变仍通过，历史默认展开时失败，生产文件恢复原始字节。
- checker 10/10，真实 106 模块依赖图通过。官方生产和完整 npm audit 均为 0；第一次完整审计 TLS 失败记录保留。
- 真实 Chromium 的 configured/bind-loss 三次均通过，本地中位数 4.684 秒；全部七个 desktop 场景也通过。每个短场景只配置/绑定一次；丢 ACK 后读取原回执而不重发。缺 Playwright、Chromium、构建及非法空场景均失败。
- Windows 核心夹具恢复必要 pywin32 路径后，诊断 copy probe 由 pywintypes 失败变为通过；本机 symlink 权限不足。最终 GitHub Windows 全量已实际执行该夹具的 symlink 路径并通过；其普通完整套件为 3198 项，1977 成功、1221 原有跳过、零失败/错误，执行 198.652 秒、job 271 秒。
- MCP 夹具共享单个 SQLite DBAPI 连接的缺陷实际复现为 90 次中 1 次错误；文件数据库独立池连接后 90/90，通过时保留两个并发连接及原 UNKNOWN 语义。
- 独立审查未发现未解决问题；独立定向复跑 Python 33、Composer 14、checker 10 项通过。Windows 增量另行审查并重跑 31 项，26 成功、5 原有 POSIX 跳过。

## Evidence boundary

公开 CI 链接提供最终完整日志；原始基线失败、逐条 ID、缓存/阶段时间、反例与本地回执均保留。基线 PG 的旧尾部输出限制仍存在，覆盖迁移证明使用的是完整基线普通 Linux 成功 ID。浏览器为真实 Chromium 加合成 API；66 个最终 PG 跳过和 1221 个 Windows 跳过保持显式，真实供应商及外部服务/容器 opt-in 未执行部分仍不算已验证。
