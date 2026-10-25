# Design

## Context
基线931f7c3。复用ResearchServer：真实研究root暂停于原native wait，真实唯一child完成；fixture仅暂停应用observe_waits，保留原未确认custody而非伪造任务表。

## Decisions
硬停该测试服务后，在相同隔离PG/工作目录启动新的bare core进程，不导入研究包/部署装配，不重新注册研究组件或适配器。新进程仅增加受fixture-control保护的只读事实与原observer单次调用探针，避免靠睡眠猜清理已发生。

通过原owner HTTP检查旧job可读；原task/run/operation/child身份不变，原operation未明确闭合时task不能terminal/settle/reclaim，预算held保留。显式驱动既有observer后仍成立。健康及通用资源GET成功，研究HTTP404；原发布catalog保留而不新增种子。记录原始不确定性，不要求伪造新UNKNOWN状态字符串。

## Risks / Trade-offs
移除全部注册不同于保留missing-hook声明，本测试不注入额外owner来帮助core识别。若原native已停止与实际custody不一致，报告真实结果，不降低positive-stop要求。隔离库只在测试正常清理时删除；日志仅合成运行身份，fixture秘密不输出。
