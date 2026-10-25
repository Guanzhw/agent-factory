# Verification (in progress)

基线90f3a131；spec-first9de16ab，完整请求指纹整改b5c60eb。准入与原输入已实现；普通budget root现复用既有完成事务进行预算结算，最终独立review与集成验收仍待完成。

- 旧portable四模块首轮30通过/0跳过，4.643秒；补budget配置归属/期限/caps和隐私断言后31通过/0跳过，6.846秒。
- Ruff受影响文件通过，Pyright 0 errors/0 warnings。
- 实际PG/native queue首轮6项5通过1error，21.791秒。唯一error为并发fixture误用先返回的合法unconfirmed收据(taskId=None)，不是重复派发；两请求结束后只读刷新原receipt，targeted修正1项通过，5.502秒。原有submit==1/单allocation/双方隐私断言保持，无期限变更。
- 已有通过证据覆盖：完整请求fingerprint三个字段故障注入（materialChoices/connectionRefs/inputValues），并发单原消息/allocation/task及原输入；prepared恢复及禁用后原task只读；事务rollback无孤立hold；普通instances不能绕过禁用endpoint；P3复用一个allocation。字段故障注入修改现存prepared fingerprint，未声称完成一条真实新连接配置旅程。
- 首失败保留：`/tmp/af-research-next-evidence/private-budget-pg-first.log`；targeted修正：`private-budget-pg-receipt-fixed.log`；portable：`private-budget-portable-first.log`、`private-budget-portable-expanded.log`；静态：`private-budget-pyright.log`。
- 一次性PG只创建/清理本测试隔离数据库，PG串行槽已释放。无真实模型/GPU/付费外部服务。未计量fixture caps仅证明轮次/工具及身份机制，不证明真实token/money预算；P7真实QA必须配置实际模型额度并单独验证。
- 未完成最终组合验收或独立代码review，不将5+1分开通过记为最终同head整组验收。

## Ordinary budget root completion

- coordinator补充Store/scopes通用budget-only completion context；现有应用callback优先，复用原observer原子terminal/usage/storage结算，不增加scanner或读取副作用。
- 实际PG `test_owned_native_finalization_postgres` 13项通过/0跳过，11.176秒，退出0；原始日志 `/tmp/budget-only-finalization-pg-first.log`。其中3项新增budget-only场景验证UNKNOWN usage保留整个group及原allocation、scope取消后沿原身份完成、reserve扫描不得提前释放、admission failure原task无派发完成；其余10项保留既有callback/rollback/并发/缺hook契约。
- 此缺口由静态调用链分析发现，没有修前运行失败记录；上述是修后机制证据，不能伪称红绿复现或真实模型计量通过。最终同head整组消息验收、独立review与集成CI未完成。

## 最终本地组合检查（独立review前）

- coordinator串行执行 `test_private_message_budget_postgres` + `test_owned_native_finalization_postgres`：19/19通过、0跳过，46.023秒，退出0。日志 `/tmp/private-message-budget-final-pg.log`。此前首次失败及修正记录不覆盖、不删除。
- 受影响生产6文件Pyright：0 errors/0 warnings，退出0，日志 `/tmp/private-message-budget-final-pyright.log`。
- 这是当前工作树的本地组合证据；提交后的独立完整diff review与精确head集成CI仍待执行，不宣称已通过。
