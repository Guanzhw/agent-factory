# Design

## Context
基线931f7c3。复用ResearchServer：真实研究root暂停于原native wait，真实唯一child原生完成且 core 已持久封存 stoppedStatus=completed；fixture仅暂停应用observe_waits，保留原未确认custody而非伪造任务表。

## Decisions
硬停该测试服务后，在相同隔离PG/工作目录启动新的bare core进程，不导入研究包/部署装配，不重新注册研究组件或适配器。新进程仅增加受fixture-control保护的只读事实与原observer单次调用探针，避免靠睡眠猜清理已发生。

通过原owner HTTP检查旧job可读；原task/run/operation/child身份不变，原operation未明确闭合时task不能terminal/settle/reclaim，预算held保留。裸core夹具不启动observer后台轮询，只显式调用原observe_root，分离未观察与已确认停止阶段。确认原root native cancelled、原child的 completed 停止事实保持、custody COMPLETED/allStopped 且 output 仍指向原child/run后允许task failed与预算SETTLED；不得宣称科学completed、补写研究decision/terminal记录/project ending或产生后继event/精选publication。健康及通用资源GET成功，研究HTTP404；原发布catalog保留而不新增种子。

完全移除所有应用声明后，core不自动识别已移除应用的业务收尾责任；重新安装也不承诺自动补写业务终态/outbox。该边界遵循owned-native-finalization既有spec/design，不引入持久owner机制。首次过强oracle失败保留并纠正，不将真实native停止误报为未知效果。

## Risks / Trade-offs
移除全部注册不同于保留missing-hook声明，本测试不注入额外owner来帮助core识别。若原native已停止与实际custody不一致，报告真实结果，不降低positive-stop要求。隔离库只在测试正常清理时删除；日志仅合成运行身份，fixture秘密不输出。

## Completed-child oracle clarification

Full run 40228654327 at 624bf82 failed because delegated custody was COMPLETED rather than the test's expected FAILED. The test waited only for the native child ticket, not the persisted core stop seal. A deterministic read-only reproduction using actual `FactoryLifecycleObserver._facts` and `DelegatedOperations._observe` shows the distinction: with the same completed ticket and later protected failure, absent `stoppedStatus` yields FAILED, whereas a previously sealed `stoppedStatus=completed` preserves COMPLETED and original child output. The old probe did not capture the child's body, so the precise historical interleaving is not asserted as measured.

The fixture now fixes the completed-child scenario by waiting within the original 30-second deadline for both native completion and the persisted completed stop seal before killing the paused parent process. It does not require child `terminal=true`: the root owns group completion and may retain child terminal/settlement until the entire group stops. After removal, delegated custody must remain exactly COMPLETED with the original child task/run; the parent must still fail, its native ticket must cancel, and no research domain completion or new execution may appear. No set of alternative outcomes is accepted. Removal before a child's stop seal is not covered by this case; this correction does not close all removal races.
