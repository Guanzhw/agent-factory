# Tasks and ownership

- [x] 记录原205条PG/HTTP查询/原生调用/响应体/耗时基线。
- [x] backend：成员摘要分页、本地观察与明确收尾，root集成API/schema边界。
- [x] remote：只读GET保留校验，后台原回执观察及科研持久化投影；full发现科研控制误用纯读旧回执，修复后三阶段及usage定向验收通过，历史失败保留。
- [x] frontend：独立刷新、旧历史保留及跨页插入补齐。
- [x] root串行验证：PG等时间戳分页、成员隔离、GET无生命周期写（保留审计/stream元数据）、无浏览器时本地/远程收尾，同夹具前后比较。
- [x] Web完整检查/audit与真实Chromium旧历史/键盘/返回/错误流程。
- [ ] 独立复核、精确head CI、清理自建资源并更新Draft97。

## Full失败后的当前分工

| Owner | 文件范围/责任 | 状态与依赖 |
|---|---|---|
| root | 核心API、Store、远端投影与科研handoff接口；串行PG、CI、发布 | finalizing与取消持久边界已通过原capacity/storage/synthesis回归；三阶段与usage最终定向验证通过；精确head CI待提交 |
| history_backend | HTTP/personal-model分页夹具；独立复核root修复 | 7真实用例通过；独立复核完成 |
| history_remote | controlled_remote_worker、remote usage测试 | 整模块9真实用例通过；原身份与控制交界独立审查完成 |
| history_frontend | web状态与相关UI测试 | finalizing类型/说明完成，Web707通过 |
| takeover_review | scientific origin/controller及新纯读回归 | 保留各轮真实失败；围栏busy、成功claims及receipt一致性回归通过，原三阶段最终定向通过 |

完整c123 CI失败及原取消运行均保留，不将定向通过替代完整验收。#99隔离工作树只完成依赖/消费者梳理；不把功能改动混入本分支。

仅root运行重型测试并发布；worker仅合成夹具、不访问秘密或外部模型。#98已获用户35秒后非零退出授权，保持独立分支；#103 exact fast/full均通过，但本地完整失败根因仍未关闭。
