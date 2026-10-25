# Tasks

## 1. Freeze the minimal contract
- [x] 1.1 独立审查设计的普通 child 外部等待接缝与复杂度，对照真实 NativeBridge/ControlCommands/custody 源码；记录可实施结论及精确责任，不能跳过父 child 协议。
- [ ] 1.2 冻结直接进程 helper 版本/命令、选定资源 config 与原 receipt 字段；文档说明用户目标 scheduler 未定、自动安装不支持，portable schema/错误反例通过后才写接线。

## 2. Reuse native child waiting
- [ ] 2.1 以精确SSH launch/wait adapter+revision注册唯一owner hook，分离父Research等待；实现原 operation Agent结果与现observer接线，用真实PG child pause→硬重启→原run续跑、continue已发送ACK丢失、foreign ID/重复命令反例证明无新dispatch。
- [ ] 2.2 复用现 process start/custody/read 责任供 SSH adapter 使用，不延长同步等待；测试父取消与预算耗尽后零新操作、原未知 holds 保留，并记录各状态真实含义。

## 3. Add the selected SSH process backend
- [ ] 3.1 Factory保留ResourceService准入/lease，远端仅BoundedProcessAdapter原journal；实现直接进程adapter，portable测hostkey/变更拒绝/唯一映射，明确实际隔离能力；GPU fixture核GpuBinding与释放证据，环境变量单独不能释放。
- [ ] 3.2 串行真实 loopback sshd + 透明 TCP 转发运行有限 CLI，验证最终 hostkey、submit 应答丢失、断线、控制器重启、原任务唯一、取消正向停止及不确定保留；仅隔离 fixture，无真实账号。
- [ ] 3.3 实现独立SSH原结果只读port，保持tool_results唯一CLI证明不变；实际文件测试证明owner/run/operation错配拒绝、越根/symlink拒绝、归档失败不清理、来源撤回后共享失效，私有输出不默认外泄。

- [x] 3.4 Add original delegated-child read port and 16KiB private SSH output, wire exact SSH wait through it, and verify identity rejection, truncation and receipt replay without new dispatch.

## 4. Connect the research consumer
- [ ] 4.1 setup/确认约定显式选择计算资源与训练材料，沿原 root→child 与预算绑定；实际研究集成测试证明 child 原等待、真实 CLI 输出到 root 评价、负结果保留、目标修订不重置资源/预算。
- [ ] 4.2 QA 无训练工具负例与 browser 配置/缺项/未知状态验证通过；更新 P5/D01 覆盖说明，不把本机 SSH 或合成模型记成正式科研。

## 5. Review and target acceptance

- [ ] 5.0 CI keeps one original native SSH wait/restart case and portable input/wait contracts in daily selections. Manual full discovery requires all native SSH cases and the Research setup-to-delivery integration to execute without skips. The separate real loopback SSH check reports its actual host prerequisites and evidence; a missing sshd is not GPU or network acceptance.
- [ ] 5.1 对精确 base/head 完整 diff 做作者外精简审查，必要整改复审；串行组合适用 PG/独立 core/前端检查，保留首失败与清理记录。
- [ ] 5.2 获取目标最小非秘密信息并冻结执行方式、环境、预算与允许故障实验；在已明确的目标执行方式下补实际适配/验收规范（若需 scheduler），否则 D01 保持 BLOCKED，不擅选 Slurm。
- [ ] 5.3 正式目标真实训练/停止/恢复/证据验收按冻结参数完成或明确受阻；交付实际来源与限制，不能由受控测试推定 GPU、外部模型或部署通过。

## Evidence checkpoint: 8eee759

- 1.1 has an independent whole-diff/simplicity PASS for exact base d6c8f62 → head 8eee759; the earlier 13755c7 output-budget blocker and correction are preserved in [review.md](review.md).
- 2.1 has updated native PG evidence (3/3, 95.656s), but its combined foreign-ID/duplicate and final integration obligations remain tracked above rather than inferred from the test count.
- Output-budget admission correction: 40 portable passed, zero skipped; targeted Pyright zero errors/warnings and strict spec validation passed. Existing UNKNOWN replay retains its original rules.
- 4.1 remains open: the first Research case failed (35.567s); model-fixture signature correction 9661db2 is implemented but not rerun at this checkpoint.
- 5.1 remains open for combined applicable verification despite code-review PASS. D01 remains open for both missing GPU execution implementation and target-specific execution/scheduler/hardware acceptance; the CPU helper rejects GPU bindings.

## Current checkpoint: fa0b736 (supersedes pending status, preserves failures)

Completed evidence:
- Independent cumulative review: exact `5cde50a → fa0b736` PASS (72 files; all 18 production-file diffs byte-identical to the earlier reviewed production change).
- Exact [fast CI 40231189473](https://github.com/Guanzhw/agent-factory/actions/runs/40231189473) SUCCESS.
- Private original output/read port (3.4) has portable identity/truncation/replay checks and actual native output integration; no replacement dispatch is used.
- Research integration `9a048ca`: 1/1 passed, 25.758s, after the retained first failures. Browser `b88499a` PASS; latest loopback `bb10f29`: 1/1 passed, 8.608s.
- Actual continuation accepted before ACK loss and actual controller SIGKILL at `a6552d2`: 2/2 passed, zero skips, 33.152s; evidence recorded by `fa0b736`. These now supplement, rather than merely restate, the earlier native 3/3 instance-reconstruction evidence.

Open/partial obligations:
- Mixed tasks 2.1–3.3 and 4.1–4.2 are not mechanically closed by these counts. Their implemented CPU/native/research mechanisms have the evidence above; external SSH network fault coverage and any assertions not mapped in the linked verification remain open. In particular, accepted native continuation ACK loss is not lost remote submit ACK or physical SSH disconnection.
- 5.0/5.1 remain open for final combined full discovery and integration acceptance; review and fast success alone do not close them.
- GPU binding/allocation remains UNIMPLEMENTED and is rejected. Target execution method/scheduler selection and actual model/GPU/hardware acceptance remain unresolved (5.2/5.3).
- PR136 and PR137 remain Draft and unmerged. Dependency PR136's older 624 full CI40228654327 ended FAIL: combined 2068 cases, 2057 passed, 2 failures, 4 errors, 5 skips, 2091.848s. The four lifecycle errors have fixes at 5cde50a; the two failures are under investigation. No successful replacement full is claimed.

Details: [native fault evidence](verification-native-inputs.md), [Research integration](verification-research-native.md), [browser](verification-browser-ssh.md), [loopback](verification-loopback.md), [review](review.md).
