# Tasks

## 1. 契约与 wire 边界

- [x] 1.1 coordinator 分配独占文件与测试所有权，复核 design 的 root-only 支持矩阵及 hash/API 契约；以任务板记录和实际 caller 审查确认后开始生产编辑。
- [x] 1.2 wire owner 实施 remote_handoff.py 的严格 v2 envelope、完整定义 pin 校验与版本分支；便携测试覆盖 v1 固定 hash、v2 完整字段、额外字段、版本类型、定义/计划/schema/input/config 篡改和大小上限。
- [x] 1.3 wire owner 与 coordinator 核对 remote_bindings.py 的源/导入计划比较及根任务限制；测试拒绝 workflow、scientific、delegation、已有 remoteHandoff、嵌套 placement，保留原身份断言；更新对应契约说明。

## 2. 预算、能力与恢复

- [x] 2.1 authority owner 实施 remote_authority.py 的严格版本预算分支；与 wire owner 协调 remote_handoff.py 中 authority caller（禁止并发编辑同文件），以混合预算拒绝、原 hash、撤权/取消与 v1 响应兼容便携测试验证，并记录版本选择来源。
- [x] 2.2 wire owner 增加 target/receiver 独立显式 supportedApplicationContracts；默认 v1 指纹保持不变，v2 opt-in 配置纳入指纹；以声明不等于 receiver 支持、配置变化不改原操作、禁止自动降级测试验证，并记录配置格式。
- [x] 2.3 coordinator 集成 GET /execution-targets 的能力描述；UI owner 仅在分配后修改 shared/web，展示静态声明和未验证连接；通过 API schema 与 UI 测试及构建后浏览器核对支持/拒绝状态。

## 3. 确定性远程执行证据

- [x] 3.1 integration owner 编写 checksum-neutral 两服务/独立 PG fixture，复用现有 deterministic native bindings，发布含非空 config/schema/input 的变体；coordinator 串行运行并验证 adapter 原值、operationSeconds、原 native identity、事件与准确产物字节。
- [x] 3.2 integration owner 增加丢失 prepare/dispatch 回执、并发重复 dispatch、receiver 重启与 authority recovery 场景；coordinator 串行验证始终原操作、原绑定及至多一次实际效果，保留 deadline。
- [x] 3.3 integration owner 覆盖取消前后、UNKNOWN held、无 GET 后台收尾和 GET 无控制副作用；coordinator 串行验证 stop proof 前不释放容量，并运行原 v1 handoff/恢复定向回归。
- [x] 3.4 coordinator 更新 docs/APPLICATION_DEVELOPMENT.md 与本计划的实际支持矩阵及验证命令/结果；明确本地确定性协议证据不代表真实外部 provider 兼容。

## 4. 集成与审查

- [x] 4.1 coordinator 运行适用静态、便携及已安排的真实 PG/process/browser 检查，记录各层结果；审查 wire/authority/ledger/proof 的 hash 语义一致、权限与 UNKNOWN 未放宽。
- [x] 4.2 coordinator 验证 OpenSpec strict、git diff 和最终支持边界，整理可审查 Draft PR；未运行或失败项明确列出，不声称通过。

## Ownership and execution constraints

当前仅 planning worker 拥有本 change 目录与 docs/plans/remote-application-v2.md。生产所有权由 coordinator 在 1.1 分配；建议 wire owner 独占 remote_handoff.py/remote_bindings.py，authority owner 独占 remote_authority.py，integration owner 独占新增 fixture/tests，API/shared/schema 与生命周期交界由 coordinator 决定。同文件调整必须交接，不同时写。

worker 可运行无真实进程的便携测试与静态检查；全部 PG、服务进程、native runtime 与浏览器重型检查由 coordinator 串行安排。不得放宽原 deadline、删除独立安全断言、启动付费/真实外部模型、读取秘密或部署；worker 不 commit/push/merge。任务状态由 coordinator 维护；本次规划没有完成任何实现 checkbox。

## Workflow follow-up

- 审查和验证后由 coordinator 按已授权范围更新 Draft PR；本任务不合并、不部署。
- 满足项目归档条件后再归档 OpenSpec，保留基线与真实验证记录。

2026-10-24 root已冻结接口并分配：history_backend独占remote_handoff.py/remote_bindings.py和新manifest/bindings便携测试；root独占remote_authority.py/factory_api.py及其对应测试；history_frontend独占web目标展示；shutdown_tests独占新neutral core remote fixture/worker/integration tests。所有重型检查root串行。v2内部HandoffAuthority.contract_version默认1，v2 wire scope显式contractVersion2，receiver核对原plan；v1响应没有新增默认字段。
