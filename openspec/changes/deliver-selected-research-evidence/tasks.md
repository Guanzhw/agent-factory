# Tasks

## 1. Design and exact integration boundary

- [ ] 1.1 coordinator与独立reviewer核对本规范及实际代码可行性，确认原工具结果只读端口、单CLI材料归因与原context写artifact，不先实现私有旁路。
- [ ] 1.2 coordinator独立实现/验证所需core只读端口（当前owner/task/run、只读、不改UNKNOWN）；应用作者接入审定接口，不修改core模型或执行链。

## 2. Selected actual evidence

- [ ] 2.1 应用实现owner确认的evidence选择与兼容迁移，便携验证pin/角色/字段边界、模型不能扩大分享、旧项目缺项。
- [ ] 2.2 在原research_results步骤采集真实CLI原输出，原事务写精选artifact/selection；实际CLI+PG验证私有canary隔离、原身份、回滚及重启幂等，不重派UNKNOWN。
- [ ] 2.3 将selection接既有完成出版事务；验证负结果/技术失败/缺项/撤权分别呈现，数据库/完整性错误不吞掉。

## 3. Delivery and independent use

- [ ] 3.1 实现有限manifest和当前actor读取/导出；双用户PG/HTTP验证精确字节、派生来源撤回、损坏/超限整包失败、零命令执行。
- [ ] 3.2 使用实际确定性CLI在第二成员干净目录依包复现预定结果并新身份继续一尝试，保留原轨迹和首次失败；真实C04/D02未具资源仍BLOCKED。
- [ ] 3.3 独立完整base/head精简review、整改复审、适用静态/集成检查及证据；不将子步骤A或合成机制报告为完整自动旅程。
