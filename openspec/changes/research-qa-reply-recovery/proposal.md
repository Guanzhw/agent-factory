# Proposal

## Why

实际进程退出已复现：B 的私问回复已提交、原生 Workflow 尚未落终态时，原 run 重领会再次请求模型。先直接修复这条真实失败链，不为尚未接入的部署假设双版本兼容层。

## What Changes

- 在当前 QA 首步复用已保存的原回复，经原身份/输入与双方当前来源权限核对后跳过模型，由原生运行正常结束。
- 保留取消、未知 effect、预算及原消息读权；回复不存在时走原问答流程，关联分析不套用私问回复短路。
- 当前实现指纹自然更新；不新增 v2 组件、配置字段、UI、缓存或 worker。历史记录不删除、不重绑、不伪造旧 pin。
- 实际部署前检查目标环境是否有旧 pin 在途任务；未连接部署只记未核实，发现真实在途先保留原运行版本完成再切换。

## Capabilities

### New Capabilities

- `research-qa-reply-recovery`: 受原执行身份与当前来源权限约束的已保存私问回复恢复。

### Modified Capabilities

无已归档 capability；补充既有 QA 和自主协作的真实退出边界。

## Impact

基线 `e52dd2774cd5ba9b2687d11bf811875e64ba1ccc`；产品改动限 `applications/research/qa.py`、`qa_workflow.py` 及必要测试，Agno 保持 3.1.0。仅本轮隔离 synthetic PG/loopback 已被验证；其他部署状态未知。旧双版本草稿已另存审计目录，旧 PASS 已取代，本稿需独立复审。
