## Context

原 content 已有不可变 publication、完整依赖和当前授权；R1 返回解封后的原 content。delivery 不需要再存同一终稿副本或为副本另设 16 KiB 上限。既有 `maximum = settings.experiment_output_bytes` 是整包预算，保留其值。

## Goals / Non-Goals

正常多轮可创建、查看和下载完整成果；超出整包预算给 413。保留负结果、20 精选附件、每个 sourceId、原 ending、原 request 幂等和源撤回。不做多卷包、截断、后台物化/恢复器或新的限额配置。

## Decisions

1. **持久格式。** 新 body 只保存原 schema=1 的元数据、recordIds、完整 sourceIds，省略 records；这些是已有不可变 publication 的身份，不是可变查询。旧行不迁移。对新旧行，读取按 recordIds 原顺序返回 `records=[original.content]`，所以现有 UI/API 无格式改动，旧副本不能绕过撤回或缺失。
2. **授权和聚合内存。** `_sources` 按原 sourceIds 逐项调用 core read，检查当前读者、作者及依赖授权；只保留 recordIds 对应内容，外部依赖正文在授权/完整性校验后丢弃。累加选定正文规范 UTF-8 字节，一旦超过 existing maximum 即 413；不把累计大正文先放进有限 JSON 结构验证器，不裁掉 sourceIds。引用元数据由原验证过的记录产生，不另造通用 JSON 框架。
3. **一致预算。** 授权事务内读取原 manifest 与 selectedEvidence.items 明确引用的附件；复用单个打包 helper 在事务外生成 ZIP_STORED，避免组包占用原 admission lock。内容中 `contentArtifact` 只作为正文传输层，既不在 selected artifacts 中也不单独导出。校验原证据 ref、size/hash；累计 UTF-8 manifest 和真实附件字节先拒绝明显超限，最后实际 ZIP 字节（含全部文件头/目录）也须 <= maximum。
4. **各端保证。** create 保留现有两阶段：原 snapshot 构造 references/ending 并读取授权证据，事务外验证整包，提交阶段复核原目标版本及当前全部来源后才持久 delivery+receipt。read 同样解封并以相同整包 helper 核对预算/选中证据后返回完整 records；download 使用同一 helper 输出 bytes。list 仍只返回已有元数据页，不新增正文缓存。原 idempotent request 先恢复原 delivery，再按当前授权/预算返回；不会扩大旧快照。
5. **兼容与失败。** 单条 content 已合法、组合/ZIP 超预算统一 HTTP 413 RESEARCH_DELIVERY_TOO_LARGE。来源撤回/缺失仍 404，哈希或引用损坏仍 409，不 blanket catch 成 413。失败 create 事务无 delivery/receipt，修正配置后同原 request 可继续；成功后的重试保持同一 id/原 recordIds。
6. **结束快照（R3）。** 新 body 增加 `ending: null | {ownerId, ...deepcopy(project.ending)}`，从与 records 同一创建 snapshot 取值。保留原 outcome/reason/goalVersion/endedAt/resourceCleanup，以及自动终止已有的 verificationStatus；不把 project ownerId 写成虚构 human/model actor，不把 not_observed 改成 stopped。结束原因全文参与整包预算。未结束则 null；旧 manifest 无 ending 不从当前项目补造历史快照。重试仍返回原 ending。UI 显示“结束依据与剩余问题（原文）”、原版本/时间/owner 与清理状态；`remainingQuestions.status=not_provided` 仍仅表示未单独结构化的问题清单，有 ending 时说明参阅原结束记录，不能继续暗示用户没有提供文字。

## Risks / Trade-offs

read 为确保与下载同一完整包合同会重新核对精选附件，最多 existing maximum 有界字节；可信小团队无需缓存或另建异步导出任务。旧 manifest 如果原来勉强达到 raw 上限但加 ZIP 头超限，现在明确 413；数据仍保留且没有伪造成功。R1 终稿正文预算与 delivery 整包预算不同职责：合法单条也可能加元数据/附件后真超整包，但不能因旧 16 KiB aggregate 人工失败。

## Migration Plan

无表迁移、回填或删除。先失败回归（两条合法长记录、中文引用正文、ZIP 边界、手动 ending 原文），再实现；串行时隙跑既有真实 PG delivery 选定证据/撤回，便携补旧格式/源依赖/真实 413 和 ending 快照/UI；独立完整 diff 审查后交 coordinator。
