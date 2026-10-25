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
