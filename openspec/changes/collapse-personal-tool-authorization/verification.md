# Verification

基线 f25c899；spec-first提交52f9031。此次仅收敛同一次同步工具授权内重复guard，不宣称已证明历史两项超时的全部因果。

## Portable / static

- `PYTHONPATH=platform:platform/tests timeout 90 .venv/bin/python -m unittest test_personal_tool_execution -v`：36通过，0跳过，0.515秒，exit 0。
- 四个变更Python文件ruff：exit 0。
- 首轮pyright缺隔离worktree `.venv` 路径，exit 1；建立指向既有锁定环境的本地symlink后，第二轮0 errors/0 warnings，exit 0。没有依赖版本改变。
- 原始日志：`/tmp/af-research-next-evidence/tool-auth-portable-first.log`、`tool-auth-pyright.log`、`tool-auth-pyright-fixed.log`。

## PostgreSQL

独占串行槽各运行一次，原期限/断言保持：

- 原authentication rejection单例：1通过/0跳过，17.346秒，exit 0；日志 `tool-auth-pg-auth-first.log`。
- 原schema failure单例，沿原外部观察wrapper：1通过/0跳过，21.549秒，exit 0；日志 `tool-auth-pg-schema-first.log`，观察 `tool-auth-schema-db-observe-metrics.json`。
- 两个命令均在上述目录的证据路径下留存日志，使用本项目已有一次性PG服务，各fixture自行创建/清理隔离数据库；未改旧数据库。观察线程已停止，串行槽已释放。

| 每callback观测 | f25c899原观察 | 此次去重 |
| --- | --- | --- |
| authorize SQL / checkout | 63 / 44 | 36 / 26 |
| credential SQL / checkout | 149 / 101 | 95 / 65 |

原观察60次authorize/16次credential，此次54/16；callback数量随时序变化，不把累计SQL差直接当同工作量收益。原schema观察30.586秒，本次21.549秒，仅一次同wrapper比较，不代表稳定耗时分布或整套提速。数字是诊断证据，不是业务通过阈值。原两项daily失败及旧观察均保留，未由此次通过覆盖。

## Limits

真实PostgreSQL与loopback MCP使用合成身份/凭据；不证明真实模型、生产身份或外部MCP兼容。没有跨callback缓存、凭据缓存、新恢复控制链或超时放宽。尚待独立完整diff审查。

## Adapter fixture follow-up

PR114 head e11e31d 的fast run40194639419出现3项adapter integration失败，原日志 `/tmp/tool-authorization-first-ci-failed.log` 保留。完整adapter模块本地首复现3失败/3项，1.070秒（`tool-auth-adapter-first.log`）。

根因是该模块native_call复用Store便携fixture但没有登记新增的原run→plan映射；authorize_tool因此KeyError并被工具边界拒绝。仅在fixture补同原plan映射，不更改产品guard、期限或断言。修后adapter模块3项与execution模块36项合计39通过/0跳过，1.834秒（`tool-auth-adapter-fixed.log`）。这同时暴露最初只跑execution模块的覆盖遗漏。

修后daily Python仅运行一次：362通过/0跳过，58.072秒，exit0，所有required groups通过；`tool-auth-daily-python-fixed.log`。本轮无PG重跑。

## Remaining shared fixture consumers

组合full40196675940的Windows检查annotations显示三项MemberMCPResources授权拒绝。普通job日志存储403，未重试受限存储；独立check annotations保存于`integration-full-40196675940-windows-annotations.json`。完整member模块Linux首复现12项7error（包含Windows跳过的CLI），不是只修三个可见MCP用例。

根因是native_call将共享Store.authorize_tool替换成返回None的lambda且遗漏原plan登记。删除该旁路，登记原plan；共享Store fixture按实际adapter.descriptor.tool_name检查，替代固定fixture_query。全部真实adapter和授权断言保持。检索该Store所有导入者，除本模块外仅adapter integration，已一并运行。最终三个完整模块51通过/0跳过，5.755秒，exit0；首失败`tool-auth-member-fixture-first.log`、修后`tool-auth-all-consumers-fixed.log`。未改产品、未PG/full重跑。
