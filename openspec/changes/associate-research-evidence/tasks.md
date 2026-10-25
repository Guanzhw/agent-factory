# Tasks

## 1. Review and concrete dependencies

- [ ] 1.1 作者外审本规范、实际A08/C02/C03映射、完整输入依赖/无复制泄漏和仅真实consumer增字段；确认复用P3/QA而非新控制链。审查未通过不实施。

## 2. Bounded trigger and original delivery

- [ ] 2.1 首次资源配置明确启用后自动处理事件、无逐条审批，验证旧未配置不冒充完整旅程；复用原QA scope/endpoint订阅；研究精选start/terminal与关联intent/outbox同事务。固定词项规则、窗口/默认fanout，测试有/无匹配、停用、额度耗尽/到期、重复/restart和回滚的原event/message/task/allocation（A05/A08）。
- [ ] 2.2 QA原event分支验证精确intent/delivery/task，保留全部input依赖；tool-free模型输出related/conditions_differ/not_related及出处。正常私问仍core reply，事件分支只写领域关联，不反向send或循环事件。实际OwnerChatModel合成wire验证非法train工具一次有界拒绝、zerochild/训练（A03/A08）。

## 3. Shared projections and actual research use

- [ ] 3.1 实现不可变关联list/detail及当前逐源core.read；所有实际peer影响模型/下游字段无旁路复制，未引用来源撤回也整体隐藏。独特canary覆盖hypothesis/conditions/goal、child文本/产物及start/terminal/ending/experiment/association读取，只留safe IDs/固定状态。实际双用户/第三用户、撤回屏障和B02浏览器下钻/刷新/空状态验收，不能编辑他人原文。
- [ ] 3.2 仅实际研究consumer使用peer输入或继承派生输出时保存原round完整来源并集与sourceAssessments，接原launch/operation；用跨round/association/摘要/目标修订的canary验证不能洗来源、不截断依赖为显示窗口；撤回前新dispatch重检，原UNKNOWN观察取消仍可完成。合成验证来源访问→适用性决定→实际child goal/operation一致，以及不适用/有理由复现，不强迫每轮复用（A03/A05/A07）。

## 4. Independent acceptance

- [ ] 4.1 独立精确base/head全diff精简审查、必要整改复审，串行PG原生路径及适用组合检查；保留首失败，不放宽断言/超时或盲目追绿。
- [ ] 4.2 正式C02/C03前冻结真实任务/模型/费用/样本/rubric：有经验/无经验配对及无关/过时负对照，独立评审可见oracle、被测agent不可见。核对真实source→decision→action和有用关联；无差异或全沉默不能靠机制PASS抵消。缺参数仍BLOCKED，D类实资源独立验收。
