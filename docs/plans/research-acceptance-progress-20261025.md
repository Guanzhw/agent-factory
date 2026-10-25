# 研究平台验收进度 — 2026-10-25

依据[最终验收契约](research-platform-acceptance-contract.md)，审计源码 `f2dd047670f2efd1394ecf5dfe62c4cace342885`、任务板 `3184155`；本文从集成提交 `551f1bf` 创建。以下是已有运行记录的只读核对，没有为整理矩阵重跑测试。**局部通过不是整项 PASS，PR 数量不是产品完成度。**

## 当前集成检查

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
