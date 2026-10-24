# Tasks and ownership

- [x] 记录原205条PG/HTTP查询/原生调用/响应体/耗时基线。
- [x] backend：成员摘要分页、本地观察与明确收尾，root集成API/schema边界。
- [x] remote：只读GET保留校验，后台原回执观察及科研持久化投影。
- [x] frontend：独立刷新、旧历史保留及跨页插入补齐。
- [x] root串行验证：PG等时间戳分页、成员隔离、GET无生命周期写（保留审计/stream元数据）、无浏览器时本地/远程收尾，同夹具前后比较。
- [x] Web完整检查/audit与真实Chromium旧历史/键盘/返回/错误流程。
- [ ] 独立复核、精确head CI、清理自建资源并更新Draft97。

仅root运行重型测试并发布；worker仅合成夹具、不访问秘密或外部模型。#98已获用户35秒后非零退出授权，保持独立分支；#103 exact fast/full均通过，但本地完整失败根因仍未关闭。
