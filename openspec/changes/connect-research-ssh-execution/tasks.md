# Tasks

## 1. Freeze the minimal contract
- [ ] 1.1 独立审查设计的普通 child 外部等待接缝与复杂度，对照真实 NativeBridge/ControlCommands/custody 源码；记录可实施结论及精确责任，不能跳过父 child 协议。
- [ ] 1.2 冻结直接进程 helper 版本/命令、选定资源 config 与原 receipt 字段；文档说明用户目标 scheduler 未定、自动安装不支持，portable schema/错误反例通过后才写接线。

## 2. Reuse native child waiting
- [ ] 2.1 实现精确原 operation 的 Agent 外部结果 handler 与现 observer 接线；以普通 factory-executor 真实 PG child pause→硬重启→原 run 继续验证，foreign ID、重复命令、UNKNOWN 不能新 dispatch。
- [ ] 2.2 复用现 process start/custody/read 责任供 SSH adapter 使用，不延长同步等待；测试父取消与预算耗尽后零新操作、原未知 holds 保留，并记录各状态真实含义。

## 3. Add the selected SSH process backend
- [ ] 3.1 基于 existing resource/credential/SSH contracts 实现单一直接进程 adapter；portable 测 hostkey/资源变更拒绝、唯一操作映射、字段与路径边界，并文档化无自动安装/无 GPU 分配承诺。
- [ ] 3.2 串行真实 loopback sshd + 透明 TCP 转发运行有限 CLI，验证最终 hostkey、submit 应答丢失、断线、控制器重启、原任务唯一、取消正向停止及不确定保留；仅隔离 fixture，无真实账号。
- [ ] 3.3 原结果与精选文件经现 artifact custody 取回；实际文件测试证明越根/symlink/跨任务拒绝、证据不完整不清理、来源撤权后共享失效，owner 私有输出不默认外泄。

## 4. Connect the research consumer
- [ ] 4.1 setup/确认约定显式选择计算资源与训练材料，沿原 root→child 与预算绑定；实际研究集成测试证明 child 原等待、真实 CLI 输出到 root 评价、负结果保留、目标修订不重置资源/预算。
- [ ] 4.2 QA 无训练工具负例与 browser 配置/缺项/未知状态验证通过；更新 P5/D01 覆盖说明，不把本机 SSH 或合成模型记成正式科研。

## 5. Review and target acceptance
- [ ] 5.1 对精确 base/head 完整 diff 做作者外精简审查，必要整改复审；串行组合适用 PG/独立 core/前端检查，保留首失败与清理记录。
- [ ] 5.2 获取目标最小非秘密信息并冻结执行方式、环境、预算与允许故障实验；在已明确的目标执行方式下补实际适配/验收规范（若需 scheduler），否则 D01 保持 BLOCKED，不擅选 Slurm。
- [ ] 5.3 正式目标真实训练/停止/恢复/证据验收按冻结参数完成或明确受阻；交付实际来源与限制，不能由受控测试推定 GPU、外部模型或部署通过。
