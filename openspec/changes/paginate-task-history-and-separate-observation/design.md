# Design

按不可变(createdAt,id)降序，cursor核对owner及实际边界行。返回{items,nextCursor}，摘要包含身份、材料版本、topic/mode/scenario、状态与创建/更新/观察时间，不包含完整definition、binding、native transcript、事件或artifact；未观察时间显式null。

Observer摘要与terminal/容量证明分离。GET不执行结算或取消。远程回执仍保留精确身份、scope和账本校验；写入转移至显式reconciliation和独立单flight后台观察，5秒单批预算防网络等待阻塞本地收尾。超时不重派发，terminal未结算仍需观察。

头页刷新保留旧页面和选择；新任务跨越一页时补读到旧头边界，避免永久缺项。tail cursor独立推进，失败区域独立，过期响应丢弃；详情维持原轮询。

前后测使用相同205条合成记录的真实PG/HTTP夹具（一条实际native执行，204条历史rejected），并非205次真实执行。测量窗口暂停fixture observer，只计请求内store SQL/native调用/响应大小/耗时。

读取隔离指不修改生命周期、账本或容量。原生权限审计仍写入agno_authz_decisions；首次events读取还在专用schema advisory lock内初始化稳定cursor的af_event_streams元数据。实测捕获20次审计INSERT及各一次stream CREATE/INSERT，测试分别精确允许，不预热掩盖，不改变鉴权审计契约。
