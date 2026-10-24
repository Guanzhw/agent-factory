# 测试清理与 CI 成本收敛

状态：**planning-only Draft；实现与验收待完成**。
基线：PR95 合并提交 `246f06541b21915392a77555e24f3f617d34de9f`；实施前重新核对该提交的源码、依赖与 CI。
建议分支：`chore/behavior-tests-ci-cleanup`。
建议 OpenSpec change：`simplify-behavior-tests-and-ci`，在实施时建立最小必要规范。

## 目标与顺序

优先删除无效、脆弱、绑定实现且缺少独立行为价值的断言，保留能发现真实产品回归的验证。
先完成开发工具依赖升级和高置信度测试清理，再按实测结果消除重复执行、加入短小浏览器 smoke。
采用一个 Draft PR、分阶段提交；仅在 happy-dom major 迁移出现独立兼容性问题时拆出依赖 PR。
所有性能收益都需由同条件前后测量确认；测试数量下降本身不是目标。

## 已有证据

- 当前重构的 Linux PostgreSQL 冻结快照：3201 项记录、3140 通过、61 显式跳过，零失败/错误，1937.326 秒，exit 0、accepted=true。
- 七组 required 为 130/130、33/33、9/9、11/11、10/10、19/19、6/6；组间可重叠，不能相加作唯一用例数。
- Linux 便携全量：3201 项、2623 非跳过通过、578 跳过、212.023 秒；本地 Web 为 61 文件、699 项通过。
- fast 初始 220/58 是选择器收集数；最终 PR95 CI 已实际执行 Python 220 项、PostgreSQL 58 项，均零跳过并 accepted=true。以上本机完整套件时间不作为 GitHub runner SLA。
- PostgreSQL 完整日志 SHA：`9230e1eed7aa315c8a3e503267598981755a81359fac35d2cbb32a285c40c317`；1097 文件快照运行后未漂移。
- 原始收集失败、旧审批/成员归属夹具失败及确定性 inode/mtime 夹具修复已经保留并在当前重构处理；后续不能重复计收益。

PR95 首轮 GitHub CI（run `40074908130`）补充了真实环境证据：

- scope 路由单元测试 9 项通过。
- frontend 698 通过、1 失败，位置为 `tests/owner-model-settings.test.ts:38`。
- 该用例 click 后还经 `verifyOwner` 并等待 WebCrypto 请求摘要，`act` 未等待最终异步请求完成；PR95 已改为等待明确请求分发，Node 24 定向重复验证及最终 CI 699 项全部通过，不能再次计为后续清理收益。
- PostgreSQL 的 ECR 镜像拉取连续 3 次被 `toomanyrequests: Data limit exceeded` 拒绝，未进入测试执行。
- PR95 已切换至 Docker Hub 的同一 `17.11` 标签和同一 SHA digest；最终 CI 已成功初始化容器、完成核心真安装与 58 项 PostgreSQL 检查。
- 官方 registry 生产依赖审计重试结果为零漏洞；完整审计仍有 4 个开发工具受影响，不能合并表述为 audit green。

最终提交 `9b3728544dc2fe370d5f0655cd282fb70e68511f` 的 [CI run 40075372069](https://github.com/Guanzhw/agent-factory/actions/runs/40075372069) 全部通过：Python 220 项用时 20.586 秒，PostgreSQL 58 项用时 168.935 秒，Web 699 项；这些是本次执行值，不是未来 SLA。远端为 fast 模式，完整套件证据仍是上述本地冻结运行。

本机 `.local/validation/` 的回执用于审查，不作为公开仓库的可用路径承诺。关键结果同时见
`openspec/changes/simplify-trusted-team-platform/verification.md:32-48`；实施时补充公开 CI 链接和对应 SHA。

## 删除、重写与保留决策

| 位置 | 决策与理由 | 保护行为及验收 |
| --- | --- | --- |
| `apps/research/tests/python/test_pubmed_retrieval.py:80-86` | **重写**：`handler=AsyncMock()` 从未传入 `retrieve()`，`assert_not_called()` 无法观察请求。 | 对非法 query/limit 传入受监控的 `httpx.MockTransport(handler)`，确认拒绝且零请求；非法 transport 类型单列 CONFIG_INVALID。保留 :193-198 已连接 transport 的异步授权回调验证。 |
| `tests/application-source-boundaries.test.ts:10-24` | **删除重复扫描**：只扫描 web 顶层和字面导入，`resolve(...)+ '/'` 还受 Windows 分隔符影响；弱于已有 resolver gate。 | 由 `scripts/check_web_architecture.mjs`、`architecture-web.json:1-8` 拥有依赖方向规则；保留 checker 的直接/间接、alias、动态字面导入和 composition bypass 负例。 |
| 同文件 :26-38 | **删除精确 import/禁词断言**：引号、注释、符号和重导出方式不应成为产品契约；文件可整体删除。 | checker 保护依赖边界，已有 `workspace-flow.test.ts` 保护入口/导航。先确认 `import.meta.glob` 约束是否有唯一覆盖，必要时在拥有规则的 checker 补最小真实负例。 |
| `tests/application-composer.test.ts:31-78` | **重写并合并**：精确 class 属性、HTML index/slice、textarea 属性顺序绑定序列化；删除无独立边界价值的 clone equality。 | 并入 `application-composer-flow.test.ts` 的 DOM 行为：新任务可访问、历史折叠、预算/工具/缺项默认可见、外部字符串为文本且无 script 节点；保留显式恢复与 API 次数。 |
| `platform/tests/test_core_runtime_boundaries.py:20-41` | **删除固定 `countTestCases()==3`**：新增合法 guard 不应导致架构失败。 | 继续验证非空发现、loader 无错、零跳过、真正成功，以及隔离进程中禁止 application 导入；必要锚点直接命名行为 ID。 |
| `apps/research/tests/python/test_retrieval_diagnostics.py:40-77,90-97` | **收敛过度防御矩阵**：hostile Python 属性、替换 `__dict__`、dict.get hook 和 HostileStage 由测试人工制造。唯一生产调用先读取 `error.code`，stage 是内部字面量。 | 依据 `orx_literature_tools.py:258-262,280-283` 和 `openresearch.py:32-36,63-70,219-234`，保留真实 adapter 错误、有限 schema、exit code、不泄露命令文本/秘密及不猜测 DNS/TLS；验证错误进入 provenance。 |
| `apps/research/tests/python/test_actual_retrieval_boundary.py:29-55` | **替代行为具备后删除 `_resource_lock` identity 断言**。 | 通过适配器并发握手确认同一任务任一时刻最多一个执行中的检索；首调用完成前第二调用等待或明确 BUSY，完成后合法后续调用仍可执行。保留真实 container ID、guardian、退出与 allStopped。Docker opt-in 未执行时明确未验证。 |
| `platform/tests/test_at10_recovery_timing.py:136-165` | **保留调用行为，删除 :153 的描述符类型镜像断言**。真实包装器 `inference_tree_worker.py:242-246` 依赖 staticmethod 调用签名。 | class/instance 调用均成功，领域失败原样保留；不能因私有符号就删除。 |
| `test_at10_observer_responsiveness.py:38-106`、确定性 inode/mtime 夹具 | **保留**：Event 握手保护事件循环与取消；rename/utime 已构造真实身份变化。 | 保留原始运行身份、停机证据与夹具前置条件；只在耗时证据指向具体浪费时改 polling，不批量删 sleep 或身份检查。 |

每个删除项需在 PR 中对应受保护行为、现有/替代用例和实测结果；只有替代证据取得后才删除独有覆盖。
不按“security”标签一概保留，也不按私有方法或短实现一概删除。

## CI 执行收敛

源码显示 full Linux 的两个入口重复发现两棵测试树：
`.github/workflows/ci.yml:64-66` 执行 `check_python.py:83-92`，:104-126 执行 `check_postgres.py:79-85`；两者复用 `discover_tests()`。
当前 PG runner 已保证单次 invocation 内唯一 ID，优化对象是两个 Linux invocation 之间的普通用例重复。

最小方案由 full PostgreSQL job 拥有 Linux 完整行为执行，Linux Python job 保留静态/架构检查；保留 Windows full 兼容性发现和本地 `check_python.py`。
实施前比较真实成功 ID、skip 理由与环境，确认 PG job 覆盖普通行为；若无数据库环境存在独有验证，保留明确短小的便携用例。
每日 fast 两条选择已由 `check_fast.py:13-31` 验证不重叠，保持该契约；不新增按 `_postgres` 文件名分类的平行清单。

保留 `test_core_package_distribution.py:138-175` 的 wheel 字节/metadata 与全模块隔离导入。
其 :177-192 的 TestClient lifespan 与真安装 gate 有重叠，先测量独有观测，再考虑合并；新 venv 真安装、真实 Uvicorn/PG 启停和清理是独立验收边界。
Linux、disposable PG、required selectors、SSH/PG 工具、独立核心安装及所有被声明为必需的覆盖缺失时继续失败；required skip/expected failure 不能满足验收。
显式 ORX/容器/公开服务 opt-in 保留准确 skip 理由，不能将未执行报告为通过。

## 开发工具、浏览器与依赖可靠性

完整官方审计报告 2 high、2 moderate：happy-dom `20.14.5→21.0.4`（major），vite `7.3.6→7.3.7`，vitest `4.1.11→4.1.12` 及其 mocker。
实施时重新审计，先小步升级 vite/vitest，再验证 happy-dom major；更新 lock，执行 Node 24/Linux/Windows 的 DOM、类型与构建验证。
Node 26 的既有 `--no-experimental-webstorage` 复现条件单独记录，升级后实测再决定是否移除说明。
生产依赖零漏洞与完整开发依赖审计分别报告；禁止 blanket `npm audit fix --force`。

本机 npmmirror audit API 曾 404/NOT_IMPLEMENTED，不能当零漏洞；CI 尚无独立 audit step，不能据此断言 CI 配了该镜像。
采用任务级显式官方 registry 审计，记录服务错误、报告与退出码；为 high/moderate 设置明确门槛并保留报告。
采集 npm/uv 下载、镜像拉取、cache hit、失败和重试耗时；PR95 已验证同 digest Docker Hub 可用，继续按实际可靠性与耗时观察，不新增 fallback registry 链或更改全局用户设置。

真实 Chromium 曾发现 happy-dom 未暴露的工具名称 HTML pattern 错误，因此短浏览器 smoke 有直接价值。
候选为现有 `personal_tools_smoke.py --desktop-only --scenario configured --scenario bind-loss`；先核对场景与当前成员工具契约、请求次数，再锁定最小覆盖。
在已有 frontend build 后运行，验证表单、保存/绑定、丢失 ACK 后不重发；其他 viewport/专项恢复仍由完整或手动验收承担。
CI 使用锁定 Playwright 和匹配 Chromium，缺包/二进制/dist/零场景均失败；本地可选条件不能成为 CI skip。
场景的 API 是合成拦截，仍需真实 HTTP/PG 原生工具验收保护所有权、凭据与调用幂等。

## 测量与完成标准

- 同 SHA、依赖、机器类型及冷/暖缓存条件记录 before/after：selected/unique/executed/skip、发现时间、执行时间、job wall time 和 runner-minutes。
- 分开记录依赖安装、镜像拉取、核心构建安装、测试发现/执行和浏览器 smoke；下载故障与测试失败分类。
- 短 fast/smoke 可测 3 次，报告中位数和范围；完整套件按必要基线和最终 gate 运行，额外重跑由具体失败驱动。
- 用实际数据提出后续预算，不预设“5 分钟”“减少 50%”或固定 3201/699 数量目标。
- 成功标准为受保护行为完整、低价值断言已移除、重复执行消失且成本变化可解释；CI 必需条件缺失明确失败。

## 实施任务

- [ ] 核对合并基线、依赖与既有修复，建立逐项删除/重写/保留映射，补充最小实施规范。
- [ ] 更新 vite/vitest，再完成 happy-dom major 兼容性验证；分别保存生产和完整官方审计结果。
- [ ] 修复未连接的 PubMed mock，删除重复源码边界检查，将 composer 改为 DOM 行为并去除固定总数与人工 hostile-object 矩阵。
- [ ] 为锁身份断言补确定性并发行为，收敛 staticmethod 镜像断言；保留真实停机、身份、预算、所有权、凭据与 provenance 验证。
- [ ] 运行定向回归与 checker 正反例，验证 class 顺序等实现变化不误报、真实配置/边界回归会被发现。
- [ ] 采集执行 ID/skip/阶段时间及 registry/cache 数据，确认环境覆盖后消除 Linux full 重复执行。
- [ ] 在 frontend build 后加入锁定 Chromium 短 smoke，验证必需依赖缺失失败与原请求无重发。
- [ ] 完成 Linux 完整 PG required、独立核心安装、Node 24 Web/Windows 和 exact-head CI，发布前后测量与全部跳过/失败记录。

## 范围与待确认事项

本轮不改权限模型、历史审批/schema、预算/取消/UNKNOWN 恢复语义，不重写测试框架，不平行化共享数据库/进程夹具，不清理历史证据或数据库/vault。
历史 `test_pr50_install_closure.py` 的 verifier/manifest 仍被 `install-pr50-handoff.sh:16-17` 消费，退休前需确认迁移入口维护承诺。
待确认：`import.meta.glob` 的唯一规则覆盖、锁定浏览器依赖安装方式、GitHub required contexts、Windows symlink 夹具权限限制以及实际 CI 成本；取得对应证据前不宣称完成。
