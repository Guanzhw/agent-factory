# P3 verification

## 最终本地机制验证

- 冻结实现便携31/31、0跳过3.423s（端点/精确内容/消息/恢复/事件回归）。
- 串行真实PG/native16/16、0跳过76.660s：同原request并发恢复、暂停发送者、预算绑定回滚和拒绝改绑/晚绑定、丢ACK与重启保持原身份；事务事件、receiver额度、双方向撤权屏障、停止准入屏障、实际后台离线交付；取消/到期后实际保留模型和工具入口拒绝且调用计数不增。均合成模型，无付费或GPU。
- 预算guard测试使用实际装配而非直接调用guard；默认core装配创建单一scope服务。事件服务不解释研究内容；scope/订阅目前仅可信应用配置，无HTTP自动赠予预算。
- final PG日志/tmp/af-research-next-evidence/p3-pg-final.log；portable p3-portable-final.log。独立完整审查由foundation_review，最终精确head复审待记录。

独立core wheel真实安装、空PG启动、原native worker与干净关闭通过；检查明确appPackagesAbsent/researchRouteAbsent/researchTablesAbsent，未启动模型。最终Ruff/Pyright0，OpenSpec strict通过。

## 首失败与修复保留

1. 初PG5项4通过1error：BaseException模拟崩溃终止TestClient portal。第二轮8项7通过1error发生于该已终止portal的fixture shutdown。改独立asyncio.run注入，再正常fixture重启，targeted1/1 10.507s。此为持久reservation+服务重启测试，不是真实OS crash。
2. 首集成12项11通过1失败：settle返回HELD，被测试误写为内部ALLOCATED。改同时验证外部HELD、内部ALLOCATED、task为空和额度占用；手动prepare测试隔离自动loop，另有真实未patch后台case。整改PG6/6 37.774s；之后结算观察修复由最终16覆盖。
3. 新撤权事务接口使便携fixture缺transaction，初23项5error；在fixture中将transaction代理到已有同连接connection，未加产品fallback或放宽断言。
4. 独立review阻断：单坏项饿死后项、stop期间recover仍可能fresh准入。已改每项attempt/error轮转及fresh admission检查，增加真实屏障；终局无task拒绝在同admission锁内确认，保留allocation hold。
5. Ruff捕获接线编辑缩进/导入错误，Pyright捕获Store新字段声明缺失，均修正。首次fast选择命令误用--list-only退出2，改--collect-only确认55 PG选择有效，未冒称执行。

## 边界

reserved但无native回执仍只观察不补派；本次不解决所有崩溃窗口最终执行。自动lineage在可信parent/task传入时校验，P5真实agent上下文接入尚未完成，不能声称已证明整条自动循环不可绕过。新应用P5–P9未完成，真实C/D参数未冻结仍BLOCKED/NOTRUN。UI后续实现及含UI合并暂停，等待用户原型确认；本变更无UI源码修改。
