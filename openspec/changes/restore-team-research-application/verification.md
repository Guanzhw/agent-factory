# P4 verification

P4只实现可选项目、研究约定、目标历史及中文入口；execution.available=false，没有start占位路由。P5–P9未完成，不能算最终研究产品验收。

## 已执行

- 后端便携6/6、真实PG/HTTP2/2（8.467s），均零跳过。PG覆盖重启原回执与历史、双用户隔离及并发目标CAS。
- Web完整检查442/442（43 files），退出0；包含独立审查整改后的11个应用DOM测试。默认core build与显式research build分别通过。
- daily Python340/340、零跳过53.337s；Python/TS架构检查零违规/缺口；Ruff、Pyright0。npm完整audit0漏洞。
- 实际Chromium、空的隔离PG、两个demo身份：登录→研究目录→空状态→项目/约定确认→刷新→项目列表正常点击→Bob直达拒绝与独立空空间→Alice退出/重登→资源入口通过。截图见evidence/p4-empty.png与p4-project.png。
- 两次自建browser server均正常native worker/scheduler关闭并退出，临时PG由IsolatedPostgres清理。父任务自建PG容器保留供后续串行测试。

## 首失败与整改

- 后端restricted sandbox下TestClient停滞，保留首次exit143；同代码允许loopback网络后通过，不调整生产期限或断言。
- 独立review发现408及刷新丢原创建请求ID；先补spec，再实现owner/project隔离sessionStorage原命令恢复，11测试覆盖原ID重试和跨用户隔离。
- 首浏览器未配置已安装browser目录，启动失败；显式PLAYWRIGHT_BROWSERS_PATH后启动。
- 真实browser发现research Vite入口hook执行过晚，构建仍是core入口；改为pre hook后研究入口出现。
- 真实点击发现material-row三列布局使项目标题被状态遮挡；改应用自有纵向卡片，正常click复验通过，没有force click。Bob拒绝提示断言从内部code纠正为实际中文文案，HTTP隔离另由PG用例明确404验证。
- 初次Pyright缺应用import root，配置applications extraPaths后0错误。

日志在本任务/tmp/af-research-next-evidence/p4-*及projects-pg-first.log；未将临时日志当公开下载附件。合成demo身份不是组织生产身份，未调用真实模型、GPU或外部账户；C/D仍BLOCKED/NOTRUN。最终精确head独立review/CI待完成。
