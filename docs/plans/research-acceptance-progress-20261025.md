# 研究平台验收进度 — 2026-10-25

依据[最终验收契约](research-platform-acceptance-contract.md)，审计源码 `f2dd047670f2efd1394ecf5dfe62c4cace342885`、任务板 `3184155`；本文从集成提交 `551f1bf` 创建。以下是已有运行记录的只读核对，没有为整理矩阵重跑测试。**局部通过不是整项 PASS，PR 数量不是产品完成度。**

前几节为按时间保留的历史检查点；当前分层结论见本文“最终本地验收检查点”。历史“运行中”和“未通过”不描述最终状态。

## 历史集成检查

- 精确 `551f1bf` 的 [full 40206239436](https://github.com/Guanzhw/agent-factory/actions/runs/40206239436) **运行中，尚未通过**。
- main `a877268` 的 [CI40205579401](https://github.com/Guanzhw/agent-factory/actions/runs/40205579401) 成功。
- #121 head `35a` 的 [fast40205859880](https://github.com/Guanzhw/agent-factory/actions/runs/40205859880) 成功；#125 head `b894` 的 [fast40205935827](https://github.com/Guanzhw/agent-factory/actions/runs/40205935827) 成功、未合并。这两个 head 缩写按协调检查点记录，不能据此推断其他提交通过。
- #124 首次 fast 有 9 个错误；夹具修复 `4a92` 后 55 项针对性通过，新的 [fast40206226531](https://github.com/Guanzhw/agent-factory/actions/runs/40206226531) **运行中**，首轮失败保留。
- 旧组合 `69d798ba5d58a4ea6c9d25c45fa17f071f165388` 的 [full40199430407](https://github.com/Guanzhw/agent-factory/actions/runs/40199430407) 成功：PG 1941 项、5 跳过，Windows 1941 项、793 跳过，均零失败/错误。它不能覆盖新增 QA、工作台及工具协议修复。

## 17 项验收覆盖

证据索引 E1–E12 位于文末。表中“缺验收”包括代码已有但操作/证据尚未覆盖完整判据；“BLOCKED”仅用于缺真实依赖或运行前参数，不能掩盖尚可实施的产品缺口。

| Case | 已运行证据 | 尚缺内容／判定 |
| --- | --- | --- |
| **A01 core 独立** | PR104 精确 `506cb4e` 独立安装、空 PG、启动关闭及 core-only 浏览器；P3 再次验证无 app 包/路由/表。[E1][E2] | 基线局部通过；新组合的独立安装、移除应用及遗留任务边界尚无最终完整证据。当前 full 运行中。 |
| **A02 空间、权限、秘密** | scoped content 4 portable/2 PG；P4 双用户；原始 artifact 私有 canary；QA 双方来源交集、私有 canary 不进入模型、未引用来源撤回隐藏整份答案。[E3][E4][E5] | 局部通过；未有当前最终版本覆盖全部列举边界的统一记录。应用侧精选原始 artifact 的共享入口尚未交付，通用 content 授权不能替代该用户路径。 |
| **A03 去重、UNKNOWN** | 实际 child/custody、丢回执、进程 SIGKILL 后同库恢复原 root/child；原请求、原消息/allocation 恢复；改配置及禁用收件人后零重派。[E4][E5][E6] | 局部通过；证据分属不同版本/层级，尚非当前完整集成验收。服务对象重建不能记为 OS 重启。 |
| **A04 事件、循环预算** | P3 16 PG/native，追加 7 个公开入口；私有消息与完成事务 19 PG；重复交付、回滚、撤权、scope 耗尽和 UNKNOWN 保留。[E2][E7] | 局部通过；未找到新研究应用完整成环问答的队列终态证据。BYOK 仅限制 rounds/toolCalls/deadline，token/费用未计量，不能声明真实费用 ledger 验收。 |
| **A05 离线 QA 无训练** | 实际 native QA、OwnerChatModel 合成 HTTP；恶意 provider `train tool_call`：wire=1、任务 failed、无 reply、training trap=0、child=0，下一问额度拒绝。[E5] | 机制局部通过，不是仅靠 prompt 检查。QA 浏览器退出/重登完整旅程尚未执行；真实模型质量另属 C03。 |
| **A06 自动记录、负结果** | pending_admission 精选记录 9 portable/2 PG；实际 child、终态记录、完成回滚、后继轮次；浏览器断言 root/child completed 和 terminal-record。[E4][E8][E9] | 部分实现、局部通过；未找到成功、科学负结果、技术失败、取消、UNKNOWN 全部真实执行分支的当前完整记录。受控模型的 `met` 不等于科学达标。 |
| **A07 改目标、停止、预算连续** | P4 历史/重启/目标 CAS；rounds portable 原 scope 后继；实际取消交错、撤权、停止证据与硬重启。[E4][E6][E10] | 代码存在但整项缺验收。最新浏览器在启动前改约定，不能替代运行中改目标、原在途操作与新目标生效的端到端验证。 |
| **A08 有范围的主动关联** | 通用事件订阅/授权/去重有机制证据。[E2] | 研究主动关联未实现；缺研究相关性规则、实际候选/收件人与无关负对照。不广播或全部不发送不算通过。 |
| **B01 登录与无 app 底座** | core-only demo＋本地合成 HTTPS OIDC；四个真实 core/API/PG 登录回跳旅程；最新研究浏览器包含登录、资源、刷新、重登。[E1][E9][E11] | 合成身份子项通过；真实外部身份服务 BLOCKED，新组合 core-only 最终验证仍待当前 full 结果。 |
| **B02 双用户完整研究旅程** | 产品代码 `9ce15e4`：demo desktop、本地合成 OIDC mobile；实际 HTTP/PG、setup 发布、约定、child checksum、终态证据、历史/刷新/重登、Bob 读写拒绝，2 场景通过。[E9] | 已实现子旅程通过；尚缺 Bob 团队读取/关联、QA 浏览器、运行中改目标、完整失败/未达标交付及成果下载复现。模型设置通过真实 HTTP fixture 创建，未走模型设置浏览器表单。 |
| **C01 真实自主多轮** | 合成模型读取实际 checksum 后决定继续/停止；真实后继及立即 stop 零 child。[E4] | BLOCKED／NOTRUN：真实模型、研究任务、指标、预算与 rubric 未冻结；现有机制不能算真实自主研究通过。 |
| **C02 团队经验配对对照** | 尚无符合契约的真实有经验/无经验配对实验。 | NOTRUN，且产品路径未完整实现：来源→决策→实际动作的团队复用及负对照缺失；真实任务/模型参数另为 BLOCKED。 |
| **C03 QA／主动关联价值** | 合成 HTTP QA 验证来源依赖、权限和恶意工具拒绝。[E5] | BLOCKED／NOTRUN：未运行真实模型质量评审；主动关联未实现，协议通过不能解除门槛。 |
| **C04 可复现、可继续成果** | 当前有真实 checksum artifact，不等于完整交付包。 | 未实现／NOTRUN：缺新应用成果包及另一成员不看原聊天复现、继续研究证据；真实数据、容差等需另行冻结。 |
| **D01 实际 GPU 与恢复** | 新应用证明本机 child/custody 与原身份恢复。[E6] | BLOCKED：无新应用实际成员 GPU/SSH 训练、断联、重附着及设备停止证据。历史旧 Research/ORX 不能替代。 |
| **D02 实际部署、归档、生命周期** | core 完成事务回滚、存储保留及历史关闭测试可作机制基础。[E1][E12] | BLOCKED／最终 NOTRUN：新应用实际部署、归档失败/低水位、活跃 UNKNOWN 下关闭重启及移除应用联合演练未完成；P8 归档/成果链也未交付。 |
| **D03 约 20 人容量** | 没有符合契约的目标机混合负载结果。 | BLOCKED：目标主机、负载、时长、SLO 与资源阈值未冻结；现云端测试耗时不是容量基线。 |

## P0–P9 完成边界

| 阶段 | 实际状态 |
| --- | --- |
| P0 | 独立底座基线已验；新组合仍需最终回归。 |
| P1 | 通用端点及稳定研究助手身份已实现，有持久化/权限/CAS 证据。 |
| P2 | 原消息、离线准入、回复与恢复已实现，有实际 PG/native 机制证据。 |
| P3 | 通用事件/预算已实现，不能外推完整研究成环协作或 BYOK 费用控制。 |
| P4 | 项目、约定、历史、入口和稳定助手关联已实现；QA 新入口浏览器尚缺。 |
| P5 | 固定 native Workflow、child、后继轮次、停止/恢复已实现并有合成验证；真实自主研究与个人远端 GPU 未验。 |
| P6 | 开始/终态精选记录已有；不自动共享任意 raw artifact。显式精选原始 artifact 产品路径和全部终态验收未齐。 |
| P7 | 私有 QA 已有 native 合成验证；浏览器未验、主动关联未实现、真实团队价值对照未跑。 |
| P8 | 有停止/未达标决定机制；完整可复现成果包、第二成员复现/继续未实现。 |
| P9 | 未完成。新 full 正在精确 `551f1bf` 运行；即使通过，也不能替代缺失的 C/D 及完整用户旅程。 |

## 证据索引与缺口

- **E1** [移除 Research／独立 core](../../openspec/changes/remove-research-verify-core/verification.md)
- **E2** [P3 事件和预算](../../openspec/changes/subscribe-bounded-assistant-events/verification.md)
- **E3** [限定内容共享](../../openspec/changes/share-scoped-application-content/verification.md)
- **E4** [新研究 native Workflow](../../openspec/changes/restore-team-research-application/native-workflow-verification.md)
- **E5** [助手 QA 验证](../../openspec/changes/add-research-assistant-qa/verification.md)
- **E6** [原 child 操作桥接](../../openspec/changes/bind-delegated-workflow-operations/verification.md)
- **E7** [私有消息预算](../../openspec/changes/bound-private-assistant-messages/verification.md)
- **E8** [P6 开始记录](../../openspec/changes/restore-team-research-application/start-records-verification.md)
- **E9** [真实工作台浏览器及持久截图](../../openspec/changes/integrate-live-research-workbench/verification.md)
- **E10** [P4 项目验证](../../openspec/changes/restore-team-research-application/verification.md)
- **E11** [登录与工作区返回](../../openspec/changes/restore-browser-workspace-return/verification.md)
- **E12** [原生完成事务](../../openspec/changes/finalize-owned-native-runs/verification.md)

QA 最终五个 case 有分次通过记录，但没有同一轮完整 5/5 绿色结果；初次 3 通过/2 失败及后续修复必须保留。若现行 full 后续覆盖它们，应追加实际精确结果，不回写旧运行。

多份 verification 仅列临时日志路径或阶段源码描述，缺完整逐 case 最终 head/run manifest；未能从记录确定的精确版本归属仍为 **unknown**，不得补猜。临时路径不是可下载附件。

`link-bounded-research-rounds/verification.md` 是已移除旧 Research 的历史 ORX 证据，不计入新应用 P5、C01 或 D01。历史 MCP 长尾根因、无整套提速证据的限制仍存在，局部通过不能关闭它们。

## 追加检查点 — 2026-10-25 16:08 UTC

本节保留并更新上面的历史审计判定；信息来自本轮协调检查点及已完成的目标验证，没有重跑测试。短 SHA 按收到的记录保留，不补猜完整版本。

### 精确运行终态与待验证修复

- `551f1bf` 的 [full40206239436](https://github.com/Guanzhw/agent-factory/actions/runs/40206239436) 最终 **FAIL**：PG 2029 项、2 failures、7 errors、5 skips，1904.628s；Windows 2029 项、7 errors、822 skips，203.273s。独立 core smoke **PASS**；不能用它覆盖整套失败。
- 7 errors 的夹具修复 [#126](https://github.com/Guanzhw/agent-factory/pull/126) 已合入 `bc776`，[main fast40208942470](https://github.com/Guanzhw/agent-factory/actions/runs/40208942470) **SUCCESS**。该 fast 不是修复后完整 discovery 的结果。
- remote 取消断言已定位为未控制后台观察顺序：修复 `a2421fb`＋`65ec5dd` 保留观察前精确 PREPARED，观察后要求精确 CANCELLED_NO_DISPATCH、同一身份及零 ticket；与 dispatch-CAS 先胜反例合计 **2 PG passed／0 skipped，9.884s**，尚待独立 review。首 full 失败保留，生产代码未改。
- 恶意 QA 已确认同一 task/run 的 queue attempt **1→2**，因此发出 **2 次 HTTP**；原 wire=1 目标失败不是可以忽略的偶发结果。修复与复验未闭合，**A05 不可计 PASS**。
- 以下精确短 head 的 fast 均 **SUCCESS**，PR 仍为 **Draft**：[#121 `ef411`](https://github.com/Guanzhw/agent-factory/pull/121)／[40209307647](https://github.com/Guanzhw/agent-factory/actions/runs/40209307647)；[#125 `ece86`](https://github.com/Guanzhw/agent-factory/pull/125)／[40209314890](https://github.com/Guanzhw/agent-factory/actions/runs/40209314890)；[#127 `5b9`](https://github.com/Guanzhw/agent-factory/pull/127)／[40209353352](https://github.com/Guanzhw/agent-factory/actions/runs/40209353352)；[#128 `18921`](https://github.com/Guanzhw/agent-factory/pull/128)／[40209360880](https://github.com/Guanzhw/agent-factory/actions/runs/40209360880)。不将这些 fast 外推为组合 full 或产品验收通过。

### 17 case 差距更新

| Case | 本检查点更新／保留的门槛 |
| --- | --- |
| A01 | `551f1bf` 独立 core smoke 通过；应用移除、遗留任务及最终新组合边界仍不能由该单项外推。 |
| A02 | 原权限/私有 artifact 机制证据保留；显式精选原始 artifact 的完整产品路径和最终版本验收仍缺。 |
| A03 | remote 取消两阶段与 CAS 反例目标通过、待 review；同一 QA task/run 被队列再次尝试的已确认事实须保留，恢复与重试控制尚未闭合。 |
| A04 | 通用事件/预算既有证据不变；队列重复 attempt 的额度与停止边界需随 QA 修复验证，不能声明研究成环终态已验。 |
| A05 | **未通过最终门槛**：恶意 QA 两次 HTTP 已复现并确认，不能沿用旧单次目标通过记录关闭问题。 |
| A06 | 自动开始/终态记录局部证据不变；完整成功、科学负结果、技术失败、取消、UNKNOWN 分支仍缺最终整合验收。 |
| A07 | 运行中目标修订与在途操作边界仍缺完整旅程；P7 关联代码新发现 projects 锁序问题，修复前不得视为集成稳定。 |
| A08 | 从“未实现”更新为关联代码 `f848c6a` 已有 50 项 portable 证据、待 review；已发现 **P1 严重度的 projects 锁序问题**。相关性、接收范围、无关/过时负对照的完整行为验收仍未成立。 |
| B01 | 本轮独立 core smoke 通过；没有新增真实外部身份服务或完整 core-only 浏览器验收，原 BLOCKED 边界不变。 |
| B02 | P7 UI `3e7` 的实际 mobile QA 浏览器通过；desktop group JSON 证据不完整，不能记整组通过。完整双用户研究、关联、运行中改目标与复现旅程仍未闭合。 |
| C01 | 无新增真实模型自主研究证据；合成多轮不替代 C01，仍 BLOCKED／NOTRUN。 |
| C02 | 关联 portable 与 QA mobile 不构成团队经验配对实验；仍 NOTRUN，真实任务/模型/预算待冻结。 |
| C03 | 无真实模型 QA／关联价值评审；恶意 QA 重试问题也尚未解决，不能外推 PASS。 |
| C04 | P8 不再仅是未实现：`210810f` recipe 修复有 **30 portable＋5 targets** 通过；旧版本实际 CLI **2 PG＋故障 1 PG** 机制通过。新 head 未整体验收，第二成员不看原聊天复现/继续与真实成果判据仍未完成。 |
| D01 | 没有新增实际个人 GPU／SSH／断线恢复证据，仍 BLOCKED。 |
| D02 | P8 旧 CLI/故障机制证据不等于新 head 实际部署、归档与关闭重启联合验收；仍 NOTRUN／BLOCKED。 |
| D03 | 没有新增目标机容量证据；主机、负载、SLO 等未冻结，仍 BLOCKED。 |

### P0–P9 阶段更新

P0 的新独立 core smoke 通过；P1–P3 的既有身份、消息、事件机制证据保留，但 QA 队列重复 attempt 尚待修复验证。P4 的项目基线不等于新增关联消费者锁序安全。P5 仍只有合成自主多轮与真实本机执行机制证据，未达到 C01/D01。P6 的限定内容共享边界不变，不能自动扩大为 raw artifact 共享。P7 新增 mobile QA 浏览器与关联 portable 进展，desktop 证据缺口、恶意 QA 重试、关联锁序和独立 review 尚未闭合。P8 已有 recipe/CLI 实现和目标证据，但 `210810f` 未整体验收，复现与继续研究门槛仍开放。**P9 未完成：首 full 明确失败，相关修复尚未形成新的完整适用验收；任何 fast 成功均不解除 C/D 的真实依赖与产品行为门槛。**

## 追加检查点 — 2026-10-25 16:35 UTC

以下记录最新机制验证与评审结果，保留前述首失败和旧时点判定；没有为文档更新重跑测试。短版本标识按协调检查点原样记录。

- core 重试围栏 `5fe414c` 独立 review **PASS**；**29 portable＋4 PG** 通过，PG 30.143s。强制 queue attempt 2 先于 observer：恶意响应仍仅 **1 HTTP**、原任务 failed、保留原保护记录；普通可重试错误仍 **2 HTTP 后成功**，并覆盖 rollback/reopen。首次 cleanup 错误保留。这关闭了已定位的恶意 QA 重试机制缺口，不把先前失败改写为成功。
- P7 关联最终 `030016a` 完整独立 review **PASS**；**51 portable＋4 PG** 通过，PG 30.389s，覆盖锁 barrier、无 association 的原团队记录进入实际 child、正常/恶意路径；最后提示修订另有 **3 portable** 通过。模型输入的 **11 个来源依赖全部保留**，界面只展示 1 个 assessment 不等于仅绑定一个来源。
- P8 当前 root `737`＋peer 增量 `bb8`：**4 PG、92.059s** 通过实际 CLI 复现、继续研究、rollback 与来源撤回，独立 review **PASS**。首次命令缺少 deployment import root 的失败保留。该证据是受控 CLI 机制，不是实际科研/GPU 交付价值验收。
- 当前组合 **27 portable** 通过；架构检查覆盖 **480**、零违规；全生产源码 Pyright **0 errors**。这些检查不替代完整 discovery。
- 正式 P7/P8 UI `2f1fb74` 完整独立 review **PASS**，**490 Web** 测试通过；真实浏览器仍在 fixture 调试，不能记 B02 PASS。该 UI 尚未创建 PR、未合并。
- main `cd50b9c` 的 [CI40211020781](https://github.com/Guanzhw/agent-factory/actions/runs/40211020781) **SUCCESS**。后端组合 `931f7c3` 的 [full40211745245](https://github.com/Guanzhw/agent-factory/actions/runs/40211745245) **运行中，非已通过**。
- [#129 QA `b105`](https://github.com/Guanzhw/agent-factory/pull/129)、[#130 QA UI `e811`](https://github.com/Guanzhw/agent-factory/pull/130)、[#131 关联 `f997`](https://github.com/Guanzhw/agent-factory/pull/131)、[#132 交付 `e9ed`](https://github.com/Guanzhw/agent-factory/pull/132) 均为 Draft，精确提交 CI 待终态；#121/#125 仍未合并。独立分支评审与目标验证不等于这些 PR head 已分别完整验收。

### 对验收 case 与阶段的影响

| 范围 | 最新判定 |
| --- | --- |
| A03／A04／A05；P1–P3、P7 QA | 原保护记录在队列重试前阻止再次调用，正常重试不被误禁，已有确定性/PG 证据及独立 review；A05 机制缺口已修，最终组合 full 仍待。BYOK token/费用未计量的边界不变。 |
| A02／A08；P6–P7 关联 | 锁序修复、完整来源依赖与实际 child 消费已有目标证据，不能再称关联未实现；尚须当前组合与完整浏览器旅程验收。精选共享不自动扩大为全部 raw artifact 共享。 |
| A07；P4–P5 | 新关联消费者锁 barrier 已验证；不能据此声称运行中目标修改的完整用户旅程通过。自主轮次现有合成机制证据不替代 C01。 |
| B02；P7/P8 UI | 正式 UI 已实现、独立 review 和 490 Web 通过；真实浏览器未完成，整项仍缺验收，旧 mobile 子场景也不能替代新完整旅程。 |
| C04；P8 | 交付、他人实际 CLI 复现/继续及来源撤回已有机制证据，不再是仅有 recipe portable；真实研究成果、数据与容差下的独立复现价值仍未验，不记 C04 完整 PASS。 |
| A01／B01；P0 | 独立底座既有证据保留；main CI 成功不能代替当前组合的应用移除/完整登录边界。 |
| A06；P5–P6 | 自动记录已有实现与局部证据；本检查点未新增完整成功/负结果/技术失败/取消/UNKNOWN 分支验收，不上调整项。 |
| C01–C03／D01–D03；P5、P7–P9 | 无新增真实模型配对价值、实际 GPU、真实部署或目标机容量结果。仍按原 BLOCKED／NOTRUN 边界，不能由 CLI、合成模型或 Web 测试外推。 |
| P9 | 新后端 full 正在 `931f7c3` 运行；前轮 FAIL、首次 fixture/cleanup 错误与目标修复均保留。当前没有完整最终交付 PASS。 |

### 正式真实验收前仍需冻结的最少输入

1. 参考研究任务、可见输入与隐藏 oracle、正式模型/参数、调用预算，以及有/无团队经验和无关/过时经验的配对判据；这些须在运行前固定，不能按结果调整通过线。
2. 可共享的实际数据、成果复现/继续方式及随机或 GPU 结果容差；受测 agent 不得看到隐藏裁判答案。
3. 实际身份服务与部署环境、个人远端 GPU/SSH 目标及明确访问授权；目标机配置、代表性约 20 人负载、运行时长、SLO 和资源阈值。

上述真实依赖之外，当前 full 终态、正式 UI 浏览器 fixture 修复与完整旅程、最终集成逐 case 证据仍是可继续执行的工程工作，不应归为等待用户选择而停下。

## 最终本地验收检查点 — 2026-10-25

本节更新前述历史判定，保留原失败；以[集成验证](../../openspec/changes/restore-team-research-application/integration-verification.md)的精确版本与分层证据为准。最终 PR 合并状态、main SHA 及合并后 CI **待更新**，这里不代填。

### 完整检查与追加检查的准确范围

- 精确 `931f7c3dc9c92c2dbe17bdf468c2e66e93708050` 的 [full40211745245](https://github.com/Guanzhw/agent-factory/actions/runs/40211745245) **七个 job 全部 SUCCESS**：PG 2073 项、5 跳过、零失败/错误，1923.095s；Windows 2073 项、835 跳过、零失败/错误，304.332s。PG required groups 19/5/102/16/10 全通过，无 required skip；独立 core、静态/架构和双平台前端通过。
- full 之后新增三项接缝验证，再与原成功重启用例同组运行：集成 `4e0e794b381dee8e2517fa602a64bec58d749915` **4/4 通过、0 跳过、65.334s**。不是“2076 项 full 通过”；2076 仅为后续 discovery 数量。
- 最终 UI 独立 **490 Web** 通过，desktop demo 与 mobile 本地合成 OIDC 的实际浏览器/API/PG 旅程均通过。模型仍为合成；真实 CLI 与真实浏览器不等于真实科研模型或外部 IdP。
- 旧 full 40206239436、QA 重试、夹具/浏览器首失败均保留。永久错误围栏修复不取消正常 transient retry；历史 MCP 长尾根因及无整套提速证据的限制没有被本轮绿灯抹去。

### 17 case 最终分层判定

“本地通过”仅覆盖契约允许的确定性/实际本地层级；C/D 的真实依赖独立列出。

| Case | 本轮结论与关键证据 |
| --- | --- |
| A01 | **本地通过**。full 的独立 wheel/空库启动关闭，加[同库移除应用](../../openspec/changes/verify-app-removal-original-task/verification.md)：原任务可读、原身份/数量不变、无研究 import/路由；未知阶段保持承诺。core 取得正向停止证明后允许 failed/SETTLED，研究业务表、terminalRecord、ending、事件和精选内容不自动回填。不承诺重装自动修复业务终态。 |
| A02 | **本地通过**。core 当前权限、双用户项目/任务隔离、完整 ZIP 私有 canary、作者写/团队读、来源撤回及派生作者也失去读取；P7 绑定全部输入依赖，P8 不导出仅为权限依赖的附件。未执行真实数据共享。 |
| A03 | **本地通过**。原 request/消息/allocation 去重及冲突；实际 root/child SIGKILL 恢复；取消 UNKNOWN 跨重启保持 task/run/operation/handle，零替代 dispatch；remote 原 CAS 先后状态分开验证。 |
| A04 | **本地通过**。已有回滚/撤权/去重/预算原语，加[实际 native 双端点循环](../../openspec/changes/subscribe-bounded-assistant-events/verification-cycle.md)：两任务、两原 scope 各一次结算，第三次准入拒绝，事件 lineage 深度 0/1/2，后续真实扫描无新增工作。 |
| A05 | **本地通过**。正常离线 native QA、受限操作预算；恶意工具响应零训练/child，强制第二 queue attempt 先于 observer 仍仅一次 HTTP；普通 transient 错误保留实际第二次成功。来源撤回和浏览器离线 QA 证据分别保留，不以 prompt 声明代替 dispatch 断言。真实回答质量属 C03。 |
| A06 | **本地通过**。实际成功、CLI 指标 3<4 的科学负结果、技术采集失败、取消及 UNKNOWN；开始/终态自动记录，分析标级且有来源；完成故障回滚及重复观察不制造第二记录。[取消接缝](../../openspec/changes/restore-team-research-application/verification-cancel-unknown.md)补齐未知阶段无终态、正向 stop 后唯一取消记录。 |
| A07 | **本地通过**。真实 desktop 在途目标 v4、原 goal3 证据和总预算保持；CAS 冲突/原 scope 续接，加取消 UNKNOWN 同库重启、父/child/cleanup 原身份和 hold、正向停止后结算。目标变更不重置预算、不替代未停原操作。 |
| A08 | **确定性机制通过**。相关正向候选、无关/私有排除、固定人数上限、重复不扩候选、not_related、当前逐源权限及撤回；实际关联不是全沉默，原团队记录即使无 association 也能进入实际 child。条件适用性/过时经验的真实质量仍属 C02/C03。 |
| B01 | **demo／本地合成 OIDC 子项通过；真实外部 IdP BLOCKED**。core-only 登录/主页/资源、URL/刷新/退出重登与跨用户隔离；不把本地 OIDC 冒充生产身份认证。 |
| B02 | **确定性真实浏览器旅程通过**。desktop/mobile 覆盖启动、实际 child、自动记录、团队关联/读取、在途改目标、not_met、三角色 ZIP、Bob 权限/撤回、URL/刷新/重登；[持久截图与 JSON](../../openspec/changes/connect-research-associations-and-delivery-workbench/verification.md)。业务 API 未 mock，模型与本地身份仍合成。 |
| C01 | **BLOCKED／NOTRUN**。有实际结果驱动的合成多轮机制，无正式真实模型自主研究；需冻结研究任务、模型/参数、预算、指标及 oracle/rubric。 |
| C02 | **BLOCKED／NOTRUN**。来源→决定→实际 child 的机制已通，尚无真实模型有/无团队经验配对及无关/过时负对照。不能以消息数或合成引用判团队价值。 |
| C03 | **BLOCKED／NOTRUN**。离线 QA 和相关关联机制已通，真实回答/适用条件/有用通知质量未评；禁止训练的硬边界不替代质量评估。 |
| C04 | **真实科研层 BLOCKED／NOTRUN**。实际 CLI 三角色包、另一成员干净目录复现与新身份继续、完整来源撤回已通过；未以 C01/C02 真实成果、冻结容差完成独立科研复现。 |
| D01 | **BLOCKED／NOTRUN**。原 child/UNKNOWN 本地恢复通过，不是个人远端 GPU/SSH 的实际 job/device、断联和取消证据。 |
| D02 | **实际目标部署层 BLOCKED／NOTRUN**。本地 artifact 回滚、来源保留、core 生命周期和同库移除通过；实际部署存储/低水位/归档失败/关闭期限联合演练仍需目标环境与冻结策略。 |
| D03 | **BLOCKED／NOTRUN**。无目标机约 20 人混合负载；成员数存在、云端 CI 耗时均不是容量证据。 |

### P0–P9 与独立审查

P0 独立 core 与移除接缝、P1 身份、P2 消息/离线 QA、P3 事件/有界循环、P4 项目/约定、P5 native 研究/原操作恢复、P6 精选共享、P7 问答/关联/完整来源、P8 选择证据/交付/实际 CLI 复现的确定性实现和适用本地验证已具备。**P7/P8 当前无已知确定性实现缺项**；这不是用户价值与真实科研全部验收。P9 的本地 A/B 层已收敛，外部身份子项及 C/D 真实资源门槛仍开放；最终 main/合并后检查尚待更新。

独立审查精确范围详见[集成验证的 review 记录](../../openspec/changes/restore-team-research-application/integration-verification.md)：core 围栏 `551f1bf→5fe414c`；P7 `3e73b724→030016aec28b79966d4e486083baf1cc4da8e512`；P8 初审与 recipe/source 整改、peer CLI `7377298→bb8d8a3`；集成至 `53b6be0`；追加 A06/A07 `931f7c3→2d7e816`、A04 `931f7c3→b024fe9`、A01 `931f7c3→7881c71`；UI 证据 `2f1fb74→55e1419`/等价发布 `0a5a1e4` 与纯 driver 清理 `0a5a1e4→f14bdae`，均有作者外 PASS。原锁序、来源截断/旁路、配方有效性等问题整改后复审；不按代码行数机械宣称简化。

历史发布检查点（下方合并记录更新其状态）：本轮 [#130](https://github.com/Guanzhw/agent-factory/pull/130)、[#131](https://github.com/Guanzhw/agent-factory/pull/131)、[#132](https://github.com/Guanzhw/agent-factory/pull/132)、[#133](https://github.com/Guanzhw/agent-factory/pull/133)、[#134](https://github.com/Guanzhw/agent-factory/pull/134)、[#135](https://github.com/Guanzhw/agent-factory/pull/135) 的最终合并/精确 head CI 核对 **pending**。上述组件评审和组合运行不能冒充每个 retarget 后 head 的审查/CI；最终 main SHA 和主线 CI **pending**。

仍需的真实输入沿用前节三组：正式任务/模型/预算/盲评与配对判据；实际可获取数据和复现容差；外部身份、部署/GPU 访问和目标机工作负载/SLO。参数在正式运行前冻结，结果不能反向修改通过线。

### 发布收尾检查点

截至 main `da783091a4fb77ee656383c57c1407d122dede05`，#104–133 均已合并。正式工作台 #125、问答界面 #130、主动关联 #131、精选成果/继续研究 #132 已合入；最终证据界面 #134 和本验收记录 #135 尚待合并。#134 精确 `505a316504157ce47c177bae38b1a71152bbd3cf` 的当前 main 完整 diff 与原审范围逐字节一致，独立复审 PASS；对应 fast 40215526281 尚待终态。部署没有执行，未配置实际目标主机或暴露入口。
