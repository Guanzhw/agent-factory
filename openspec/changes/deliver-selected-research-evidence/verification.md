# Verification — 无 peer 来源的具体 CLI 消费者

基线1b58d79；应用规范0fbf1fd及撤回整改be53406先于实现。已摘取独立审定原CLI只读端口9ad11a0/be25678（本分支687f7ed/2f86bfd），未修改该core实现。

## 实际行为与证据

- 真实MemberToolOperation/个人资源binding → 原native Workflow/child → MemberCliAdapter执行本地Python → core原effect回执 → owner固定三字段 → parent原application_context精选artifact → 原完成事务共享。程序自报source/recipe标producer_declared，模型不能选更多字段。
- manifest只存应用领域表；目录只有opaque ID/作者/时间。全部原source权限在短admission事务读取；字节快照后退出事务再序列化/ZIP。generic content没有派生manifest副本。无source仅owner可读。
- 实际PG扩展组2/2通过、0跳过，28.034秒，exit0：`/tmp/research-delivery-native-expanded-first.log`。原生两成员各自资源绑定、不同root/allocation继续；Bob从包内source/recipe在干净目录实际执行得到预定value=3,target=4；完整ZIP不含独立private.txt未选canary；原source撤回后目录/正文/导出拒绝；另一用例用双向屏障验证来源撤回与读取/下载快照锁序。PG串行槽已释放，fixture数据库/进程清理。
- 此前实际PG首轮1fail、5.074秒：`/tmp/research-delivery-native-first.log`。fixture错把registrationRef当connectionRef，start preflight409且零派发；补真实connections.bind，保留断言/期限后单例通过1/1、15.594秒：`/tmp/research-delivery-native-binding-fixed.log`。此旧单例仅检查manifest未含canary，扩展组增加完整ZIP字节断言且将canary置于独立未分享文件，避免源码literal影响隔离判据。
- 便携首baseline25项1fail，2.758秒：`/tmp/research-delivery-portable-baseline.log`。原迁移断言未包含新增nullable selection；保持原字段完整相等并显式加selection=None后，新旧29项通过5.023秒：`/tmp/research-delivery-portable-first.log`。最终29/29通过3.776秒：`/tmp/research-delivery-portable-final.log`。覆盖空源owner-only、逐源撤回、无generic副本、ZIP锁外、超限、原field选择及selection回滚/幂等；新增pin不匹配断言另见targeted记录。
- Ruff通过。应用Pyright正确配置platform/applications/deployment路径后0errors/0warnings：`/tmp/research-delivery-pyright-final.log`。首次裸路径check有5个导入配置错误及1个真实missing局部变量类型错误（已初始化修正），保留`/tmp/research-delivery-pyright-first.log`。

## 尚未关闭的门槛

- P7 peer-derived来源并集与附件需core sourceContentIds及peer_sources实际接口集成；本分支尚无该路径，不宣称peer撤回传播通过。manifest仍需按已确认spec继承全部依赖，不只安全shell。
- selection回滚目前便携事务证据，实际native artifact写后故障/完成出版回滚的P8专属PG尚未执行；既有通用完成事务证据不能冒充此具体消费者全部故障覆盖。
- 模型是合成fixture，实际CLI仅证明执行/来源/复现机制；正式模型自主研究价值、科学容差、真实GPU/远端归档C04/D02仍未验收。无付费/新凭据/部署/UI改动。
- 独立完整diff审查、精确head集成CI尚待执行；未推送/合并。不以子步骤或这些成功计数宣称完整P8交付已通过。

## 精选采集实际故障回滚

新增实际native单例首轮1/1通过、0跳过，13.199秒，exit0：`/tmp/research-delivery-capture-fault-first.log`。原parent结果步骤已实际写入首artifact后注入RuntimeError；原事务回滚artifact/selection，原root失败完成，closed child保持1个DONE CLI effect、总2task，没有重派。日志中的注入异常是测试预期，并未吞错转成成功。该证据关闭上述“实际artifact写后故障未执行”缺项；出版callback专属故障和peer来源集成仍需分开判断。

## 配方审查整改与源权限依赖

- 独立审查指出配方truthy判断不能证明dependencies/data/expected可用；规范81e8555先明确当前三角色字段契约，代码改为有限类型/非空expected/有限标量判定。无实际remainingQuestions字段时明确not_provided，不用空集合伪称没有疑问。
- 30项便携通过、0跳过，17.859秒：`/tmp/research-delivery-recipe-fixed.log`。进一步实际capture负例验证坏配方不写artifact且保留缺项，5项通过、0跳过，1.593秒：`/tmp/research-delivery-recipe-capture.log`。Ruff通过。
- 已摘取审定source authority四提交（本分支878e50f/e9d6d3a/30ecf97/0628996），未另改core。manifest保存全部原sourceContentIds权限并集，并单列recordIds标识本项目显式选择的出版物；不能因某内容仅是依赖就把其附件也偷偷打包。
- P7 rich projection/完整peer union尚待应用接口最终集成与实际验证，不外推上述无peer运行已验证它。当前review整改后的精确head PG整组尚未重复，旧成功仍按各自版本记录。

## Source-bound publication integration follow-up

Spec 535ae70 adopts the independently reviewed simplification: core content stores and authorizes the full selected publication; no application shadow body or read-back proxy. Existing delivery implementation already uses that interface. Added portable coverage checks full sourceIds vs selected recordIds, rich selected body, no dependency-only body/artifact export, author losing a peer dependency, manifest/list/download denial and generic selected content denial.

First run `/tmp/research-delivery-peer-portable-first.log`: 6 tests, 1 fixture error (missing required publication request_id), exit 1. Fixed the fixture to use the actual publish contract; `/tmp/research-delivery-peer-portable-fixed.log`: 6 passed, 0 skipped, 1.345s, exit 0. Ruff and whitespace checks passed. These use real core content permissions with portable storage and synthetic execution; they do not establish actual P7 native consumption or PostgreSQL concurrency. P7 final reviewed round publication merge and final serialized PG integration remain outstanding.

## Final combined native/PG delivery boundary

Independent validation checkout: `/workspace/agent-factory-peer-delivery-validation`, base `73772989537c25ad4a3e7a1c8a4eabd0e16f595c` (P7 full source-bound publications + P8 selection/delivery + permanent-error queue fence). Added an actual native CLI case where Bob's original team record is shown to the synthetic model, Alice executes the original CLI child, and the three selected artifacts inherit that original source. Alice can download before withdrawal. After Bob withdraws the source, even derived author Alice cannot read the generic selected publication/artifact or delivery/list/download; task identities remain unchanged. Full dependency IDs remain separate from selected export record IDs. No application shadow-body port is used.

First command `/tmp/research-peer-delivery-integrated-first.log`: omitted deployment from PYTHONPATH, collection ImportError, exit 1; no test body or database creation occurred. Corrected runner environment only, preserving tests and deadlines:

```sh
FACTORY_TEST_DATABASE_URL=<isolated synthetic PG server> \
PYTHONPATH=platform:applications:deployment:platform/tests:applications/tests \
timeout 150 .venv/bin/python -X faulthandler -m unittest test_research_delivery_postgres -v
```

`/tmp/research-peer-delivery-integrated-path-fixed.log`: **4 passed, 0 skipped, 92.059s, exit 0**. The group also covers actual artifact-write fault rollback without CLI replay; both admission/withdrawal lock orders; and another member reproducing the exported recipe in a clean directory then continuing under a new owner task/allocation. Fixture worker/scheduler shutdown completed and isolated database cleanup returned normally. Ruff and whitespace checks passed. This is real native queue/MemberCliAdapter/PostgreSQL/local process evidence with synthetic model decisions, not real-model team-value/C04 or remote GPU/D02 acceptance.

The later P7 prompt-only correction `030016a` was not in this PG base. This new fixture already constructs sourceAssessments solely from actually displayed peerEvidence.sources, not the complete authorization dependency set; no claim is made that this run evaluates real-model prompt compliance.

After applying the existing prompt-only correction as `d55e82b`, its complete portable association module passed **11/11, 0 skipped, 3.678s, exit 0** (`/tmp/research-peer-delivery-prompt-portable.log`). The PG group was not mechanically repeated for a prompt text change; the original base and synthetic-model limits above remain explicit.
