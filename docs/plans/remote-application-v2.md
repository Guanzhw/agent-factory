# 规划：通用 v2 应用的远程执行契约

状态：Draft 规划；实现与运行验收尚未开始。基于可信团队重构 PR #95 的合并提交 `246f06541b21915392a77555e24f3f617d34de9f`。
建议 OpenSpec change：`support-v2-remote-application-handoff`。

## 问题与结果

成员应能将一个受支持的通用 v2 应用交给远程 receiver，同时保留本地执行的不可变输入、绑定和预算。现有 v2 远程拒绝是文档明确的能力限制，本项扩展该能力。

- `platform/agent_factory/application_schema.py:82-100,127-153`：v2 使用 schema 验证的 application config 和 `operationSeconds`，v1 保留旧配置与 `experimentSeconds`。
- `platform/agent_factory/composition.py:225-226`：本地计划保留 v2 标记。
- `platform/agent_factory/remote_handoff.py:34-38,163-170,194-211`：远程导入只接受 v1 及其固定字段。
- `docs/APPLICATION_DEVELOPMENT.md:119-136`：记录 v2 本地支持与 `REMOTE_CONTRACT_UNSUPPORTED` 的远程限制。

## 实施范围

1. 为一个选定的中性应用/runtime 冻结 v2 wire contract：schema/input/config、执行绑定、操作时间、产物来源与 receiver 支持声明。
2. 保留冻结的 v1 reader；v2 在真实 wire 边界验证一次后归一化到共享内部执行契约。
3. prepare、dispatch、恢复、继承、取消和产物读取全程保留原版本、内容身份与原回执。
4. 未支持的 receiver 明确拒绝；目标页面展示已知能力限制。已有 prepare 或未知回执按原请求核对。

## 验收

- [ ] 两个真实服务进程与独立 PostgreSQL：发布一个 v2 应用，准备、派发一次，通过 native receiver 完成并读取状态、事件及准确产物字节。
- [ ] 丢失 prepare/dispatch 回执、并发重复派发、receiver 重启和取消前后，都保持原身份且不额外启动效果。
- [ ] 执行 adapter 收到准确 v2 配置和时间上限；混合版本预算、错误 schema/input、未知版本在新效果之前拒绝。
- [ ] 原 v1 handoff 与恢复回归继续通过；构建后的浏览器展示目标支持/拒绝状态。
- [ ] 发布实际支持矩阵，将本地确定性协议验收与外部服务兼容性分别记录。

旧 v1 定义与 hash 不改写，版本不自动降级，UNKNOWN 不重放。本项不扩展集群调度或承诺任意第三方 receiver 兼容。

## 顺序与待定项

可独立于多应用装配实施。先选择一个 v2 应用和 receiver/runtime，确定支持声明位于目标描述还是 prepare 响应，并决定 receiver 接收完整 schema 还是受校验的不可变定义引用。第一版支持 root handoff 即可，未支持的嵌套 placement 保持明确拒绝。
