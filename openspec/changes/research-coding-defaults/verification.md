# Verification

## Scope

基线 `b93e87841d3fae8fe48396c6d2cd7f88e000608b`，规划 `28e74c91139d8b186da586c6fa4d3a988b92be78`，产品 `6fe00dbb40b8848fffd728f50003b4f81ce98d59`。只改三个已有配置默认及既有测试/启动说明；无新工具、数据迁移或运行机制。Agno 保持3.1.0。

## Evidence

| 边界 | 实际结果 |
| --- | --- |
| 规划独审 | 非作者全diff审查；1次Go DeepSeek审查20.997秒HTTP200、订阅计费cost=0，有可见结论且人工核对。严格spec通过。 |
| 产品独审 | b93→6fe00累计7文件审查及simplicity通过；作者与非作者各自48便携回归通过，ruff通过，作者pyright零错误（14项既有Windows模块警告）。 |
| 普通启动 | 真实PG/Agno queue。未设置三个执行参数覆盖，真实Settings/会话options为32/120/300；实际Agent cap32、worker期限300、OwnerChatModel请求期限300。 |
| 实际工具 | 新会话执行9次真实命令，包含等待实际子进程计算的unittest，9.019秒通过；本轮15.601秒。不是等待300秒的超时压测。 |
| 旧配置/记录 | 同一隔离数据库先以显式8/8/60保存旧会话和seed Plan；服务重启后读取原Plan不变、零模型请求。旧会话显式下一轮仍为8/8，第9次工具被protected_denied，实际8个DONE副作用/文件8行。不是自动重放已完成任务。 |
| 模型范围 | 本片运行验收20次SCRIPTED HTTP，零外部模型请求。已有真实Go公开仓库功能链和独立206测试复跑见上一片，不将本次脚本验收称为实模。个人模型输出仍需按提供方配置，缺省4096未改变。 |
| 原始失败 | 首次QA在模型/工具执行前误用Headers.update关键字参数；原失败保留，仅修测试调用为字典。无产品改动或未知副作用重试。 |

独立运行脚本及原始回执保留在协调环境 `design-audit/research-coding-defaults-20261028/runtime-qa/`，成功目录 `run-1793231490822360885`；真实临时数据库和工作目录已清理。审查记录分别为 `plan-review/review-28e74c9.json`、`review/6fe00db/review-6fe00db.json`。这些是本地验证产物，不是用户部署地址。

此前公开仓库case禁止child运行命令来自QA脚本额外分工提示，非用户产品权限要求；继承工具授权允许该目录查询。child执行ls仍属提示遵守失败，保留原case FAIL，不将其归因harness越权，不加新防御代码。实际修复成果与该提示测试分列。

## Remaining

准确最终head的full CI与适用发布门禁尚待。旧持久Plan额度不回写，但当前worker的原生cap/期限会影响等待和收尾。没有新浏览器/真实GPU/SSH/目标硬件容量或部署验收；全站易用性继续原roadmap，下一片先改善实际长回复/子助手结果的阅读与停止反馈。
