# Verification

任务勾选由 coordinator 对照当前源码、真实回执与独立复核后维护。下表记录验收结果和回执名称，原始日志与截图由维护者本地留存；完整集成结果、日志 SHA、实际跳过和平台限制在后文列明。

| 任务 | 已核对证据 |
|---|---|
| 1.1、1.2 | `auth-task-evidence.md`：身份及凭据相关 138 项通过；最后原生配置边界修改后 25 项真实 SQLite/PostgreSQL API 测试通过。包括普通工作流、会话隔离、禁用、管理员迁移、HTTP/WebSocket 令牌边界及无执行的 schema 管理拒绝。 |
| 1.3 | `member-callsite-linux.log` 125 项、`member-callsite-autoresearch-pg.log` 5 项、`member-callsite-candidate-pg-final.log` 1 项通过；生产代码旧 require/current-policy/reviewer 调用扫描为空。 |
| 1.4 | `account-browser-receipt.md`：真实浏览器创建、启停、编辑及管理员标记；成员无入口、直接请求 403。coordinator 已查看页面截图。 |
| 2.1、2.3、3.2 | `endpoints-notes.md` / `endpoints-linux-postgres.log`：114 项通过且零跳过，实际 HTTP、HTTPS/SNI、自定义端口/路径、三类 SSH 密钥、无科研依赖 SSH、共享调用及旧句柄撤销；另有共享模型/远程真实 HTTP 和 PostgreSQL 回执。 |
| 2.2 | `integration-vault.log`：21 项通过；coordinator 核对 local_credentials 实现与真实文件/SQLite 测试，覆盖 12 并发创建者、重启复用、密文和归属。备份要求已进入操作文档。 |
| 2.5 | `integration-core-install.log`：新 wheel 安装及真实 Uvicorn/PostgreSQL 生命周期 accepted=true，科研包缺席、普通资源入口、持久 vault、原生队列和关闭均已验证；`integration-core-assembly.log` 5 项通过。 |
| 5.1 | `execution-policy-combined-final.txt`：77 项、零跳过，旧写接口 410、成员直接运行、历史归属及配置拒绝；`MEMBER_EXECUTION.md` 记录迁移。 |
| 5.3 | `work/member-tools-postgres.log`：3 项、零跳过；提前启动的另一工作进程解析后来创建的成员工具并原生执行，服务重启保留原任务/运行与请求幂等；独立复核的原 2 项亦通过。 |
| 5.4 | `bootstrap-task5.4-linux.log`：46 项、零跳过（含真实 PostgreSQL）；另有调用方 125 项、AutoResearch PostgreSQL 5 项和候选执行 1 项。历史发布物 verifier 保留。 |
| 3.1、3.3 | `resource-sharing-http.log` 24 项、`resource-sharing-models-postgres.log` 12 项、`resource-sharing-native-postgres.log` 1 项通过；工具的跨成员实际调用、旧句柄撤回/凭据撤销/账号禁用及跨进程恢复另见 member-tools 和独立审查回执。`resource-privacy-independent-postgres.log` 独立验证当前目录可见性；私有名称不再泄露。 |
| 4.1、4.2、4.3 | `member-publication-exact-tools-linux.log`：63 项、零跳过，含 17 项真实 PostgreSQL；覆盖旧配置与审批历史跨重启保留、作者发布生命周期、动态工具精确绑定及其他成员的同名工具隔离。发布页面测试包含于最终 `web-final.log` 的 699 项完整检查；成员发布与原有三份指导文档同步更新。 |
| 5.2 | `execution-boundary-followup-final.txt` 37 项、零跳过，确认每次模型调用仅一次资源检查。`execution-independent-review.md` 记录原始同名工具重现已关闭、祖先预算仍受约束；独立复验便携 37 项、Linux/PostgreSQL 9 项、发布 2 项通过。 |
| 5.5 | `final-assembly-independent-review.md`：真实装配、vault、部署及原生入口检查通过，Linux bootstrap 5 项通过；发现的 Go 入口旧配置修复后 `member-go-runner-pg-final.log` 15 项、零跳过。`integration-env-template.log` 核心/科研、演示/生产四种模板配置通过；当前操作文档和废弃模块链接已独立复核。 |
| 2.4 | `work/member-tools-linux-native.log` 142 项、零跳过，`work/member-tools-postgres.log` 3 项、零跳过；实际 CLI/MCP、原生调用与工作进程恢复通过。`member-tool-browser-results.md` 验证真实 Chromium 配置/发现/共享/绑定、原生 MCP 执行和撤回；正好一次实际工具调用，撤回后没有新增调用。 |
| 3.4、6.3 | `account-browser-receipt.md`、`root-member-browser-results.md`、`remote-browser-results.md`、`ssh-browser-results.md`、`member-tool-browser-results.md` 覆盖账号、四类资源及成员发布执行。coordinator 实际操作 Alice 模型/应用与 Bob 模型页面，下载并独立校验真实 checksum 产物；其他分工使用独立浏览器账号会话与真实服务回执。Windows SSH 明确失败及 Linux 成功分别记录；当前部署未启用可选 personal-agent 会话接口，不据此声称远程科研会话已验收。 |
| 6.4 | 身份审查发现通过真实 HTTP/WebSocket 回归关闭；共享和执行的独立原始重现均复验通过；`final-assembly-independent-review.md` 中 Go 配置和当前文档发现已关闭。coordinator 核对最终装配、绑定、所有权/历史读取和浏览器变化，保留 `linux-custody-review.md` 中原主线相同元数据写入的检测限制。 |
| 6.1、6.2 | 最终 Linux 便携 3201 项中 2623 通过、578 跳过；完整 PostgreSQL 3201 项中 3140 通过、61 显式跳过，七组 required 全通过且 `accepted=true`。Web 699 项及类型、格式、架构检查通过。Windows 完整运行和定向补验的实际限制单独列明；原始失败及修复证据保留。 |
| 6.5 | `openspec-handoff-final.log` 严格验证通过，`openspec-apply-final.json` 为 26/26 完成；`final-workspace-preservation.json` 记录原目录 HEAD 与干净状态、交付分支和未改动的 uv.lock。最终源码差异仅为文档；交付说明、服务清理和独立证据审计均完成。 |

除标明 `work/` 的文件，日志路径均相对 `.local/validation/`。浏览器截图主要在 `output/playwright/`；远程服务的 `remote-*.png` 位于 `.local/validation/`。原始失败日志保留：首次 Windows 全量 3151 项中 58 失败、371 错误；后续全量收敛至 3176 项中 13 失败、38 错误。旧夹具迁移及实质问题修复后的完整验收结果见下文。

独立审查确认的原生 WebSocket 令牌边界已补真实回归；全局工具目录的私有名称暴露、同名工具覆盖，以及当前 Go 入口和操作文档旧配置问题均已修复并复核关闭。完整测试发现的旧成员身份夹具与 Linux 测试环境差异已收敛，并纳入最终冻结快照验收。

Linux 便携全量第三次运行了 3199 项，17 失败、19 错误、578 跳过；日志 `python-linux-full-3.log` 保留。其后针对实际失败修复旧身份 mock、原生 Linux stdlib 夹具及其他明确问题。两次更早的收集失败分别由语法错误和旧辅助方法引用引起，未计为测试通过。

浏览器发现并修复工具名称 HTML pattern 在 Chromium UnicodeSets 下的转义问题后，最终 `web-final.log` 为 **61 个文件、699 项全部通过**，lint、TypeScript、构建通过。本机 Node 26 使用 `NODE_OPTIONS=--no-experimental-webstorage`；未设置该标志的初次 DOM 环境失败保存在 `integration-preparing-node26-failed.log`，CI 使用 Node 24，复现条件已加入开发检查文档。全局 `ruff-final.log`、`pyright-final.log` 通过；Python 架构检查 714 模块、Web 架构检查 106 模块，均为零违规和零覆盖缺口。两个 fast 测试选择器收集检查均通过（3201 项发现，便携选择 220、PostgreSQL 选择 58）；它们是选择器检查，不计作实际执行。

最终 Linux 便携全量 `python-linux-full-4.log`：**3201 项、零失败/错误、578 跳过，212.023 秒**。快照 `/tmp/agent-factory-final-20261023T193354Z-20759` 包含当时当前源码；仅在快照中将 9 个已封存探针规范化为 LF，逐项证明规范化后的 SHA 与原主线及现有 pin 相同，未修改 pin。跳过包括未启用数据库、工具链/平台条件和显式 opt-in 场景；数据库验收另跑完整 required-set gate。日志 SHA-256：`04f4e9cc2900bb87c4011acc85439261bf0469671828d51de269fcf1f660ef94`。

Windows 完整检查 `python-windows-final.log`：3194 项、零断言失败、2 个 setUpClass 错误、1220 跳过。核心包分发遇到 WinError 1314（当前用户无符号链接权限）；运行时包分发的初始失败已定位为本次生成的 `work/.uv-cache-linux` WSL 符号链接被 sdist 收集。随后同一 Windows Python 在干净源码快照中完成运行时包分发模块 **4 项通过、零跳过**，独立构建 wheel 和 sdist 也通过，见 `windows-package-final-receipt.md`。为使当前工作树也能正常打包，在根 `.gitignore` 增加 `/work/`；最初未锚定的 `work/` 被 Hatchling 匹配到 checkout 的绝对父路径，导致 VCS 忽略规则失效，修正后当前工作树实际 **4 项通过、零跳过、7.103 秒**，见 `windows-package-working-tree-final-receipt.md`。这两次失败和成功日志均保留。未重跑 Windows 完整套件，未修改 Windows 权限；核心包的 3 个用例仍受符号链接权限限制。Windows SSH 验证返回现有 POSIX 运行时限制的明确错误；同流程已在 Linux 后端与真实 SSH 服务验证成功。

完整 PostgreSQL gate 使用独立冻结源码、真实 PostgreSQL/原生队列和可用 pg_dump/pg_restore。第一轮旧选择器导致收集失败；第二轮完成 **3201 项、17 失败、43 错误、61 跳过、2063.476 秒**，`accepted=false`，原始汇总、失败标识和跳过理由分别见 `postgres-full-2-summary.json`、`postgres-full-2-failure-headers.txt`、`postgres-full-2-skip-reasons.json`。这些失败中的旧审批/成员归属夹具及已证实的 Linux 元数据测试不确定性均按下述证据收敛，最终第四轮取得完整通过结果。

第二轮已知失败的定向收敛均保留原始日志：`control-remote-linux-postgres.txt` 初次 41 项中 38 通过、1 失败、2 错误，其中未再改动的远程执行和远程控制模块 15 项全部通过；`control-authority-linux-postgres-final.txt` 重跑控制命令和原始身份模块 26 项全部通过，覆盖原先 3 个失败，合计 41 个独立用例取得通过证据。OIDC 全模块 4 项通过；个人工具装配全模块 7 项通过。改动分别迁移旧角色/审批与资源所有者夹具、停用外部 OIDC 的精确 401 边界，以及新增共享动作的精确列表。原生 HITL、UNKNOWN、取消、请求身份、固定错误码和原配置回执断言继续验证。

该轮随后发现 OpenResearch workspace 仍断言默认 vault 未启用；`workspace-postgres.txt` 记录实际响应、精确五个 provider 的断言修正及完整模块 **2 项真实 PostgreSQL 通过、零跳过**。Candidate 两个模块中的废弃 reviewer 参数和 bootstrap 材料作者夹具同样修正，`candidate-postgres.txt` 记录 **6 项真实 PostgreSQL 通过、零跳过**，原进程/native ticket 身份、停止确认和不重复派发检查保留。

已冻结的第三轮仍包含这三个旧夹具，其完整结果为 **3201 项、1 失败、2 错误、61 跳过、2004.120 秒，accepted=false**；失败标识恰好对应上述三例，没有新增失败家族。`postgres-full-3-summary.json`、`postgres-full-3-failure-headers.txt` 和 `postgres-full-3-skip-reasons.json` 保留实际结果；`postgres-full-3-postrun-integrity.json` 确认 1097 文件在运行后无变动。

最终第四轮从最新源码启动于 `/tmp/agent-factory-final-postgres-20261023T200531Z-RsXwqE`；1097 文件的复制前原始 SHA 和快照 SHA 逐项核对，清单 `postgres-full-4-source-sha.json` 的 SHA-256 为 `e5692df7d3e18b85b46ee8a60af1cdbc297ea840e944b7d554ba96fd008d742b`。结果为 **3201 项、3140 通过、61 跳过、零失败/错误、1937.326 秒，退出码 0，accepted=true**。七组 required 分别为 **130/130、33/33、9/9、11/11、10/10、19/19、6/6**，没有 required 用例跳过。跳过全部属于显式 ORX/容器/工具链、Chromium 或公开服务 opt-in，准确理由见 `postgres-full-4-skip-reasons.json`；实际浏览器验收另有上述回执。`modelLive`、`externalRemoteVerified`、`realCredentialsUsed` 均为 false。

完整日志 `python-linux-postgres-full-4.log` 的 SHA-256 为 `9230e1eed7aa315c8a3e503267598981755a81359fac35d2cbb32a285c40c317`；汇总见 `postgres-full-4-summary.json`。`postgres-full-4-postrun-integrity.json` 确认冻结的 1097 文件在运行后无变动。当前工作树与快照的原始 SHA 差异仅为开发说明和 OpenSpec 收尾文档，最终差异清单见 `postgres-full-4-current-source-drift.json`。

`root-browser-cleanup.json` 确认本次 3137 应用、6926 本地资源服务和四个 coordinator 浏览器会话已关闭，相关 PID 与监听端口均不存在。浏览器数据库、配套 vault/runtime 与截图/请求证据保留。SSH 与 MCP 分工服务/会话的关闭分别见其浏览器回执。

两轮数据库 runner 完整退出后，coordinator 核对 UID、命令行和专用目录，关闭 PostgreSQL PID 809 与 SSH PID 2480。`final-test-services-cleanup.json` 记录 pg_ctl 正常退出 0，两个 PID 及 55432/55433 监听端口均不存在；数据库、配套 vault/runtime 和全部验收证据保留。

`final-evidence-audit.md` 对原始测试日志、独立安装 JSON、截图、浏览器网络和实际服务账本作了只读核对。已修正不可复算的跳过子计数、仅存工具输出的局部 Web 数字、跨轮用例计数表述、远程截图目录，以及账号回执五次 PATCH 的数字；实际验收边界按上述回执保留。

交付草稿的独立复核进一步明确：CLI 与 SSH 的进程运行都依赖 POSIX，Linux CLI 验收不能作为 Windows CLI 支持的证明。升级需将当前审批配置迁移到 `member-self-service` 并移除 TTL / `tool_policies` 构造项；无 execution manifest 的旧计划保留读取，重新组合后才能执行，已有任务及 UNKNOWN 操作继续按原身份恢复。对应契约见 `docs/MEMBER_EXECUTION.md`。

验收基线为 `0fac6de0a67e6add73aa2d7dad7d8de5e275efea`，实现分支为 `refactor/trusted-team-platform`。原工作区的 HEAD 与内容保持不变，提交和合并状态以关联 PR 为准。升级操作与执行限制见 `docs/MEMBER_EXECUTION.md`；原始本地交付说明和验收回执继续保留。
