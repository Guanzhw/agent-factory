# 独立审查

审查者：`/root/audit_crosscheck`，非实施作者，仅维护本文件。R1 已审实现不替代本次方案或后续代码复审。

## R2/R3 合并方案首审 — NEEDS_FIX

- 精确范围：R1 基线 `d9f92acffcfd6937c4c43ad8c3ddc205e6e1b9f6` → 方案 head `26e63f94e712aa50a6d73c432c8c1f62b528a50e`，5 个规范文件，产品/测试未变。coordinator 已授权把同一交付快照的 R2/R3 合并。
- 聚合方向可行：原身份快照替代完整正文副本、统一 UTF-8 manifest/精选证据/实际 ZIP 上限、保留两阶段创建和事务外组包，均复用现有合同。R3 保存原 ending/owner、旧行不补造历史、remainingQuestions 不声称原文缺失，范围合适。
- **需补 ending 的既有来源保护。** `projects._protect` 根据 `peer_sources.project_dependencies(projectId)` 隐藏 ending，而现有 delivery 的 sourceIds 只来自已发布 terminal records。某轮已经消费 peer、但尚未终态或因授权撤回没有 publication 时，它的依赖不会由 recordIds 推导出来。新增原 ending 正文若沿用这些 sourceIds，可在项目详情已经隐藏原文时从新成果取回；这不是假设任意外部攻击，而是新增载荷遗漏现有来源合同。
- 最小修订：在同一创建 snapshot 中，将原 ending 所受的完整 project_dependencies 纳入不可变 sourceIds，并沿现有 current-source 校验复核；依赖正文不因加入 sourceIds 成为选中导出记录。新旧成功请求仍固定原快照，不在读取旧交付时动态追加当前项目依赖或 ending。补“未发布轮依赖 + ending”的正向与撤回 create/read/download/list 反例。

当前 **NEEDS_FIX，尚未放行实施**。无需新授权/存储/恢复层；提交精确方案增量后复审。

## R2/R3 修订方案复审 — PASS

- 精确累计范围：`d9f92acffcfd6937c4c43ad8c3ddc205e6e1b9f6` → `951e0e1f2344d86ba9aee8667f9906d56755078b`，5 个方案文件及本历史 review；产品和测试仍未改变。已重读全部方案及两次整改增量，`git diff --check` 通过。
- 首审的未发布轮依赖遗漏已明确整改：新 ending 记录创建时原 `project_dependencies` 身份子集，顶层 sourceIds 保存它与所选记录依赖的完整并集；创建及提交、read/download/list 均复核。旧交付不读当前项目补造历史；依赖-only 正文不导出，当前交付 owner 也须有效。
- 第二次窄反例进一步修清现有语义：`core content.read` 允许来源作者读自己的 personal 记录，而 `ResearchPeerSources.require` 对项目依赖要求 team。现在仅 `ending.sourceIds` 这个固定原子集额外检查 team，覆盖同 owner 撤回；普通 selected records 保持原 owner/personal 可读合同，不把所有来源一律收紧。无需新权限层或依赖当前可选服务是否安装。
- 聚合/预算与消费者接线可实施：复用一个完整包边界，UTF-8 manifest 一次计数、只导出明确精选证据、包括实际 ZIP 头部；同一快照读取原字节、事务外组包，提交前复核原目标与固定全部来源，失败不留新 delivery/receipt。原 records API 与 UI 全文保持，旧含副本行从原身份重建，ending 原文/owner/版本/时间/清理事实不推断、不裁剪。
- **方案 PASS，可开始失败回归和最小实现。** 实现仍须独立按精确完整 `base..head` 复审；重点核对两条合法长记录、R1 中文外置正文加 20 精选附件、实际 ZIP 等号/超界、旧格式/重复请求、未发布轮与同 owner 撤回、普通 personal 正向、owner 停用、两阶段创建来源变化，以及 UI 完整 ending/无快照表述。不要把本 PASS 或 R1 的 PG 回执记作 R2/R3 已运行证据；PG 时隙仍由 coordinator 安排。

## 基线等价与未发布轮分类增量 — PASS

新工作树基线 `e4afcb6eb230ad079f13ac87dc5e3d581701b390` 只在 R1 已审产品上补原 reviewer 文档及 coordinator 任务勾选。新 spec `103ec594396010f97f20b1ed15aca49e0f9f376d` 与上述 `951e0e1f` 的 R2/R3 方案目录完全相同；原方案 PASS 适用于该等价内容。

另审 `103ec594396010f97f20b1ed15aca49e0f9f376d` → `244a9d63b984802eeea8c304c8fb2af2c9c7dfd8` 的 3 个文档文件：补充 terminal 已存在但没有 terminal_record 时的 `round_not_published:<id>` 缺证标记，与原 `round_not_terminal` 互斥；已有其他正常记录也不能掩盖这项缺失。旧交付仍保留原快照，不动态回填，不补造正文或改科学结论。该小项方案 PASS，可实施；这次未审工作区中正在进行的其他产品实现，代码仍待完整复审。

## 完整实现首审 — NEEDS_FIX

- 已审累计 `e4afcb6eb230ad079f13ac87dc5e3d581701b390` → `d7d180a704d6b1f28a223126f8db1394c207c843` 全 11 文件，独立运行 `test_research_delivery_contract -v` 为 9 tests / 0 skip / PASS，diffcheck 通过。新聚合、正文与证据分开计数、实际 ZIP 上限、ending 原依赖与 UI 接线均已检查。作者 baseline 7 项首跑 3 failures/3 errors 及 UI 首败已核对。
- **兼容性需修：目录被新增包预算阻断。** coordinator 提醒 `_sources` 同用于 list，reviewer 独立确证这会拒绝旧合同已经允许保存的交付。直接加载基线 `e4afcb6` 的原 delivery 类，在同一 SQLite、同一 `experiment_output_bytes=1024` 下，含 2016 字节合法 inline 记录的旧 create 成功、旧 list 返回 1 项；新 list 因 `_sources` 的正文累计预算返回 413，使整页元数据不可列出。这不依赖配置升级后变化；旧 create 原本只限制 16 KiB manifest，下载不能打包的旧快照仍能列目录。
- 最小复现与实际输出保存在 `/workspace/cross-pr-audit/r23-list-boundary-check.py`、同名 `.json`。输出源码 head `564056ca30e64a9ac5fd867fdee492137482d431` 与 `d7d180a` 的 delivery 相同，其间只有 UI 两文件补 Agent 分析标记；fixture 为真实 SQLite 存储、mock scope/native，不是 PG。
- 期望最小修复：list 仍逐一检查 core 内容、ending 原子集 team 和当前 owner，但不收集正文或按完整交付包预算累计；完整 create/read/download 继续共同预算，不返回半包。添加旧 create 接受但整包不能导出时目录仍可列出，以及撤回仍隐藏的回归。不要 catch 所有 413 后泄露未授权元数据，也无需新缓存/恢复层。

当前实现 **NEEDS_FIX**；补充该目录语义短方案后再修代码并完整复审。PG/npm 验证尚未据此记成最终通过。

## 目录兼容方案增量 — PASS

精确范围 `564056ca30e64a9ac5fd867fdee492137482d431` → `4a2001b68bbd4cde1f2dbc950f386b0bd28c2114`，仅 design/spec 两文件 5 行。目录继续完整的当前成员、原来源和 ending team 检查，逐项丢弃正文，不收集 records/累计整包预算；同一旧快照 read/download 仍明确 413，撤回后目录隐藏。已检查该最小方案与原目录责任一致，不引入捕获 413 的授权旁路。方案 PASS，可实施；修后完整代码仍须复审。

## R2/R3 修后完整实现复审 — PASS

- 精确累计范围：`e4afcb6eb230ad079f13ac87dc5e3d581701b390` → `20fe2f027b4fcda8e2b135f336fc61c1aa045682`，13 文件。已按前次完整实现、所有整改和最终文档增量逐项复审；最终仅 3 个产品文件（delivery 服务、交付详情、类型），未修改 native workflow pin、执行/恢复路径或核心内容合同。全范围 diffcheck 通过、树干净。
- 目录回归已最小修复：`include_records=False` 只改变收集行为，所有来源与 ending team/owner 检查仍先执行；没有吞 413 的旁路。独立原基线源码→当前同 DB/同预算脚本在 `db49d9c0` 返回与旧目录完全相同的 1 项元数据，前后 JSON 均保留。最终 head 与该探针的产品代码等值；并非把配置变更假设当作旧支持状态。
- 独立在产品修正 head `2f0cb98138b1a9dceb6429b81a8b1c07a5ba3f00` 执行 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=platform:platform/tests:deployment:applications:applications/tests /workspace/agent-factory-cleanup/.venv/bin/python -m unittest test_research_delivery_contract -v`：**10 tests / 0 skip / PASS**。覆盖旧目录超限仍可发现、read/download 413、撤回隐藏，以及双长记录、中文正文加 20 精选证据、真实 ZIP 等号/超一字节、原 ending 全文/缺证分类、同 owner 与未发布轮来源、两阶段撤回。该产品代码到最终 head 未变。
- 持久快照仅引用原不可变 records，读取完整还原；来源-only 正文不进入导出，正文载体不重复计为附件。create/read/download 共用 UTF-8 manifest/精选字节/实际 ZIP 上限，组包在授权事务外，创建提交前复核固定全部来源和版本。旧快照不动态补 ending 或新轮次，真实超限无新成功回执。
- R3 保留原 reason/outcome/owner/目标版本/时间/cleanup 和已有 Agent 分析属性；UI 原文使用既有 pre-wrap 样式，未把 owner 伪作具体 actor。ending 固定依赖子集单独保留当前 team 语义，普通 selected personal 记录仍可由 owner 读取；终态无 publication 继续明确缺证，不改原科学结论。
- 已核对真实 PG 两项 CLI/peer 撤回在 `2f0cb98` PASS；第三项手插非法格式 fixture 首败如实保留。`db49d9c0` 仅改该测试为真实 native stop→真实 create，双向锁等待与撤回拒绝不减弱，受影响一项 3.673 秒 PASS。旧生产 create 始终有 recordIds，未为不支持的 fixture 加产品 fallback；不把首次 3 项写成全过。reviewer 未重跑 PG。
- 作者最终 portable 19 PASS、前端完整 check 53 files / 492 tests PASS、两类 audit 0、Pyright 0 与所有静态/架构证据已核对。新的浏览器 E2E、真实模型/GPU/生产 IdP 未运行；verification.md 如实限定 DOM、SQLite 与真实 PG/native/CLI 的范围。
- 结论：上述完整 R2/R3 范围 **PASS**，已发现的问题均经方案修订、实现整改和独立复验，无剩余阻断项。任务勾选与最终组合验收归 coordinator；整批 Draft/merge hold 不由本审查解除。其后 reviewer 文档/任务勾选的纯文档增量须单独登记，不能冒充新运行验证。
