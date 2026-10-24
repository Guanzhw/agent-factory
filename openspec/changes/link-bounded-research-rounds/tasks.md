# Tasks

## 1. 持久归属与预算

- [x] 1.1 coordinator 核对最小 API/schema、锁顺序和文件 ownership，记录与 #102 交界；验收产物为明确分工与无反向锁序的调用图。
- [ ] 1.2 core owner 实现 local scope/round allocation、root binding 和轮内账户接入；新增便携契约与 PG 测试验证全轮 cap 预留、两轮实际累计、无活动/user 双 hold，并记录账本字段说明。
- [ ] 1.3 core owner 实现原证据结算与 UNKNOWN 保留；PG 测试覆盖重复 settlement、冲突证据、用量超预留、撤权后仍记账、无停止证明不退款和只读 inspect。
- [ ] 1.4 application owner 实现 activity/round 唯一约束及同事务 successor intent/allocation；PG 测试证明并发 continue 只建一轮、预算不足不留 free successor、原 deadline 不重置。

## 2. 本地 toy 与基线承接

- [x] 2.1 recipe owner 增加独立 iteration recipe/provider revision 的受信任 baseline pin；便携测试证明仅允许原 seed 或前轮已验 candidate、拒绝路径/任意源码/外owner，旧 TOY_FILES hash 回归不变，并更新 recipe 支持说明。
- [x] 2.2 recipe owner 接通原 ORX task-local provisioning、实际 source artifact 和 result 验证；root 串行运行真实进程验证第二轮 baseline 字节来自第一轮 candidate，MSE 16→0 后 0→0。
- [x] 2.3 application owner 实现独立评价驱动的严格改善晋升、平局/回退/失败停止；便携测试覆盖篡改回执、错误 dataset/evaluator pin、缺失产物，输出 sourceArtifact 而非伪造 checkpoint。

## 3. 原生恢复与应用生命周期

- [ ] 3.1 application owner 将持久 round intent 接到原 composition/Store reservation/NativeBridge.submit，保持原 request/native 身份；新增 PG/native 测试覆盖预留后、task 绑定后、回执前崩溃，记录不可重派状态。
- [ ] 3.2 lifecycle owner 经 ResearchServices 显式安装有界 pending-intent 扫描与关闭；验证无 GET 仍能推进已批准意图、shutdown 先停后继准入、取消/撤权/deadline 阻止新效果且原 UNKNOWN 仍占用。
- [ ] 3.3 coordinator 串行验证真实两轮 ORX/native/PG，保留旧单轮、scientific 三阶段和 shutdown 回归；报告三阶段 val_bpb fixture 与 toy MSE 的不同证据范围。

## 4. 可观察性与集成

- [x] 4.1 root 与 UI owner 实现 activity API/schema 和谱系/预算/停止原因展示；API与前端测试验证 BYOK token/money unavailable、owner 隔离及 GET 无写，实际浏览器验证重载恢复。
- [ ] 4.2 coordinator 完成适用静态、便携、PG、native/process/browser 检查，记录真实命令/结果/未验证项，更新本计划和支持文档，OpenSpec strict 与 diff 检查通过后整理 Draft PR。

## Ownership and constraints

实现由 coordinator 集成，真实验收与未覆盖项见 verification。实际文件 ownership：core owner 独占新增 local_budget_scopes.py 与 usage_ledger.py；application owner 独占新增 research_iterations.py 和必要 autoresearch.py 接入；recipe owner 独占新增 iteration recipe 及 orx_local.py/local_orx_profile.py 的最小复用 seam；lifecycle owner 拥有 services.py/assembly.py，必须先与 #102 worker 交接。root 拥有 core/schema/API 跨边界集成和最终检查，新增 tests 逐文件分配，禁止同文件并发写。

workers 仅便携测试与静态检查；PG、真实 native/process、ORX 和浏览器由 coordinator 串行执行。不得提高已有 deadline、generic child/depth cap、弱化 UNKNOWN/取消证据、启动付费或真实外部模型。worker 不 commit/push/merge/deploy，任务状态由 coordinator 维护。

## Workflow follow-up

- 完成审查后由 coordinator 按已有授权更新 Draft PR，不自动合并或部署。
- 满足项目归档条件后再归档，保留原失败与验收记录。
