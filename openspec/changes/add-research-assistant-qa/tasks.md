# Tasks

## 1. Dependencies and independent design review

- [ ] 1.1 作者外审完整spec及最小HTTP，核对无第二ACL/消息执行链、无过早通用化；确认core reply_for_task完整input dependency语义及当前身份/内容撤回事务边界。
- [ ] 1.2 集成已审core私信预算/原输入/原回复端口；未有reply前禁止用反向send或app答案表填补。视觉门槛已解除；C/D仍保留未冻结状态。

## 2. Stable identity, setup and configuration

- [ ] 2.1 实现owner唯一助手、不可变配置归属和新researchAssistantId非破坏项目列；实际旧数据迁移、并发创建、配置CAS、跨owner与旧assistantId含义验收（A02/A03）。
- [ ] 2.2 QA固定本地EnvironmentLimits和三个顶层native步骤显式装配；复用setup窄QA草稿/明确publish及有限scope配置。配置/发布不调用模型；错误/撤权/过期不续额；core无app仍独立（A01/A04/A05）。
- [ ] 2.3 接最小HTTP与已确认UI：助手目录、owner配置、私有提问/原回复/来源不可用状态。真实浏览器区分demo与生产身份，刷新/重登/原请求恢复不造数据（B01/B02）。

## 3. Original private QA and evidence boundaries

- [ ] 3.1 context核对原message/task/config；有限team研究候选逐条双方read交集；原task保存全部实际输入依赖集合，重复/重启不换来源。私有金丝雀/凭据/他人task永不进模型（A02/A03）。
- [ ] 3.2 model工具为空，record验证显示引用subset并向core提交完整输入依赖。实际native/PG测试正常问答、恶意来源及伪造上下文：GPU/训练/child dispatch为零，原模型预算正确消耗；合成机制不冒充C03。
- [ ] 3.3 受控撤回屏障覆盖输入中未引用的B、答复提交/读取、会员禁用；整段派生答复隐藏。原回复ack丢失、服务重启、UNKNOWN核对不新增task/预算/反向消息（A03/A05）。
- [ ] 3.4 作者外按精确base/head审全部diff、整改与复审；保留首次失败，运行适用静态/独立core/HTTP/native/browser检查，不以mock或旧core通过替代consumer验证。

## 4. Remaining P7 value path, separately verified

- [ ] 4.1 在上述身份/QA稳定后细化并审有限相关关联的具体规则与HTTP/spec，再复用原P3事件实现；不新增向量库/worker/全员广播，验证相关/无关/过时/无权及去重（A08）。
- [ ] 4.2 接ResearchRounds原context/decision/action来源链，保留适用条件、采用或拒绝理由及真实实验动作；有理由复现允许，不能强迫每轮复用或必然提升。
- [ ] 4.3 正式C02/C03前冻结真实任务/模型/预算/rubric/样本，真实模型对照有经验/无经验并加入无关/过时负对照；评审者可见oracle、被测模型不可见。缺依赖BLOCKED，不因协议通过关闭团队价值或D类验收。
