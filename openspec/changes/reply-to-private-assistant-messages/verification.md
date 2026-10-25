# Verification

基线c851204；spec-first207bf39，独立规范审查允许实施。本次实现为原消息nullable JSON回复，不新增消息、预算或执行。应用QA仍需传入模型实际接触的全部依据来源；core不能从正文推断来源完整性。

- 便携首轮4模块29/29通过、0跳过，2.919秒，退出0：`/tmp/private-replies-portable-first.log`。
- 最终便携5模块37/37通过、0跳过，6.544秒，退出0：`/tmp/private-replies-portable-final.log`。包含真实SQLite内容权限、旧表列迁移、所有读取入口撤回投影、幂等/冲突/身份/输入限额和非权限错误传播。
- 真实PG首轮4/4通过、0跳过，24.780秒，退出0：`/tmp/private-replies-pg-first.log`。使用实际main装配与原native task、合成模型；验证并发回复唯一且零新增submit、实际旧表删去新列后重新装配迁移并保留原身份、撤回先取得admission锁阻断回复、回复及读取先取得锁时完成原合法快照而后续读隐藏。测试数据库独立创建/清理；PG槽已释放。
- PG进程启动后对产品代码做了唯一等价整理：从`with store.transaction()`+`store._connection.get()`改为`with store.transaction() as conn`直接取同一连接；没有改变锁/SQL/判断，最终便携与Pyright在整理后执行。没有将首次证据替换为另一次PG通过。
- 受影响生产文件Pyright 0 errors/0 warnings，退出0：`/tmp/private-replies-pyright.log`；Ruff与git diff --check通过。
- 来源/会员检查按当前读取机制执行；PG屏障证明内容sharing撤回锁序，不外推所有身份变更都共用该锁。已读字节不能远程撤销。
- 独立实现完整diff审查、精确head CI待执行。没有真实模型QA质量、真实GPU、浏览器或应用团队价值验收；未推送/合并。
