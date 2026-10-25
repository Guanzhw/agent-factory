# Verification

## 当前实现与独立审查

root拥有Store/API/observer/预算集成；assistant_endpoints实现精确component selector和真实queue测试；assistant_messages实现PG故障/并发测试；foundation_review独立预审，发现完成责任随缺hook消失、停止类别投影不完整两项，已整改为显式finalizes责任及原停止事实/收尾分离。精确最终head完整复审与CI尚待完成。

## 实际验证

- Portable registry 18/18，0跳过0.020s；完整pin附加owner不替代其他owner，不另建hash链。
- PG/ledger/storage受控native事实10/10，0跳过12.988s：原usage UNKNOWN、callback及context退出失败回滚、child全组原子性、两个observer与reserve竞争、原identity/outbox唯一、retained模型/工具及新child拒绝、缺hook不释放。不是实际native queue或OS重启。
- 独立实际native queue 1/1，0跳过13.809s：真实checksum模型完成，callback写真实content/outbox后失败全部回滚；正常关闭并新建服务实例（启动observer前注册消费者），原task/run不变、模型调用数不增加、一次完成与outbox、原预算/存储释放。此为合成模型+正常实例重启，不是付费模型或OS crash。
- 首PG组4error发生于fixture storage_low_water_bytes=0违反Settings正数校验，尚未进入产品；改为1后7/7通过5.469s，扩child/并发后上列10通过。原日志owned-finalization-pg-first.log保留，不放宽deadline或断言。
- Ruff/Pyright0；其他受影响整组、独立core、OpenSpec strict和精确CI继续跟进。

原日志目录/tmp/af-research-next-evidence；queue日志/tmp/owned-native-finalization-queue-first.log。最终发布时本文件与CI链接为持久证据，临时原日志不冒充用户可下载附件。

## 限制

本core完成端口不是研究Workflow消费者已实现。UI等待原型确认，无前端修改。C/D真实模型/GPU/身份/容量参数未冻结；历史MCP时序原因未闭合。等待用量时保留任务与存储容量，不靠重派或新通知/恢复链绕过。
