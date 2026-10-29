# Verification

## Candidate and result

产品候选 `e99885d2dab6d4f0203f863cf1614eb711ebabb0`，tree `657bddc23636208b24a3cdd84eeca24c72e5c75a`；初始依赖 PR #153 的 `2f324a80ea72a78951e6ecb50d1ec0c4887b063e`。PR #153 后续 `2c9177e` 仅修 MCP 测试与交付文档，其 full 40702071114 已通过；Ready 仍待具体确认。本片尚未发布或部署，准确交付 head 的 full CI 尚未运行。Agno 保持 3.1.0。

## Evidence boundaries

| 检查 | 结果与证明范围 |
| --- | --- |
| 独立累计代码 / 简洁性 | 36 文件审查；27 个独立真实 PG 反例全部通过、0 skip，17 个 app/core 文件前后 SHA 相同，精确提交映射通过。见 review.md |
| 作者与静态 | 首轮冻结 Research 32 项、新取消修正 43 项、Core 原 41 项及新 4 项通过；这些集合有重合，不相加。新 Core 测试的两次夹具失败保留。Python 静态/架构通过，无依赖升级 |
| 前端 | 完整 npm check 567 项通过；随后唯一阻断文案增量的 28 项和类型检查通过。生产/全部 npm audit 均 0。分页撤权独立反例由 FAIL 修至 PASS；当前界面以真实浏览器另验 |
| 真实浏览器 | PostgreSQL、临时真实密码、loopback HTTPS/Chromium：自主目录/发问→B 浏览器离线 QA→A 同会话自动继续，9 次明确脚本 provider 请求；停止后迟到不复活、撤权隐藏/后续 409、GET/重复请求零新增；390px 无横溢、0 页面错误 |
| 真 OS 退出 | 消息已提交未建 B task，以及 A 自动轮已预留未建 task 两窗通过；PID174758→174936、175451→175613。保留原消息/事件/请求，只有一次 A 后续轮和一个 B task；未清 stop 或手写终态。模型是脚本，不能替代真实模型退出验证 |
| 真实 Go | `glm-5.3-flash`：A 查询目录/提问→B 回答→A 原会话继续，5 个真实 HTTP 请求（A4/B1），全部 200、Go 订阅计费、实际 cost=0，无回退。共享来源为明确合成材料，A/B 回复没有脚本替代。实际问题未附带私有目标标记，回答和续轮保留原来源 ID |

真实 Go 仅在 QA transport 内存使用既有环境 secret，临时产品 vault 存合成 placeholder；不证明生产凭据接线已经部署。所有测试服务、进程及自建 PG 已清理。证据根目录为 `/workspace/design-audit/research-autonomous-collaboration-20261028/`：`qa/version-map.json` 固定候选、源码/构建及各次实际运行，失败记录未覆盖。

## Findings retained

- 打开回复后翻页，旧详情原先不再核权；现详情沿原 questionId 独立只读核权，撤权/错误清正文、来源和采用操作。
- B admission 不能冒充执行终态；无回复的原任务失败现在显示受阻。自动 A 轮已预留但未进入主请求即结束时，不能误记已纳入或永久等待。
- 已保存提问的重启 guard 会形成自身 custody/terminal 循环；仅精确原问题回执可解除该应用阻断，既有 observer 再结算原终态，不改原状态结果。
- 实际退出发现 native-failure 清理被误当成员停止；可信取消原因现在直接传递，首次 cleanup 与每次明确取消分开。独立反例及同一 OS 原断言修后通过，没有清已有 stop。

## Known limitation and not verified

B 保存回复但原生任务尚未结束时退出，同一原 run 可重新调用只读 QA 模型。已在未改动的 PR #153 基线 `2c9177e` 单独真退出复现：同 B task/run 的 attempt1→2、两次脚本模型、原回复及其时间戳保留，不是本片创建第二个任务。若二次答案不同，源码有 `ASSISTANT_REPLY_CONFLICT` 守卫；不同答案未实测。QA 实现 hash 固定旧任务 pin，避免重算需要独立兼容方案，不能用本片两个隔离退出 PASS 覆盖这项限制。

后置权限撤回始终需由当前来源/执行/新轮准入守卫拒绝使用；本片不宣称已有 cancel 标记后每个新 cleanup 原因都会再次通知应用。科学研究质量、真实模型 OS 退出、GPU/SSH、64GB/30 会话容量、完整 OS 隔离、生产部署及全站易用性尚未验收。

## Screenshots

以下均是修复候选真实渲染、明确 SYNTHETIC QA 数据，已逐张检查，无秘密：

- [桌面自主往返](../../../docs/images/research-autonomous-collaboration/desktop-autonomous-reply.png)
- [手机停止后迟到回复](../../../docs/images/research-autonomous-collaboration/mobile-stopped-late-reply.png)
- [手机撤权后的引用](../../../docs/images/research-autonomous-collaboration/mobile-revoked-autonomous-copy.png)
