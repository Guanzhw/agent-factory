# Verification

基线 `73a4e726a434811a46c833387bafc87f909f826d`；产品候选 `5fcc4fd5d638a3931929af6e142ea50ff2e5349a`，tree `8468ed30ed4b03871a06aee0509cbab47c72d5e7`。随后仅增加本记录、验收说明及测试截图。2026-10-29 UTC；尚未合入或部署。

## Behavior and Checks

- 主回复与子助手结果按CommonMark呈现；命令输出保持原文，失败/未知常显，原任务入口保留。原始分工可展开，未隐藏停止和恢复信息。
- `finalizing`显示“正在核对最终结果”；停止中禁用重复停止，等待实际停止回执后显示“已停止”。不将模型声称完成或工具DONE回执当作命令成功。
- 最终产品候选 `npm run check`：597测试/57文件、类型、lint与core构建通过；Research构建通过，既有chunk大小提示保留。新增标准 `react-markdown@10.1.0`，无HTML/GFM/高亮插件；官方production及full依赖审计均0。此后仅改finalizing和停止按钮/测试，依赖未变。
- 非作者已完整审查初始累计diff、依赖和简洁性，并独立复核最终状态；最终文档/截图累计复审及准确head full CI在冻结后进行，未以本地测试代替发布门禁。

## Actual Browser and Process Evidence

使用隔离PostgreSQL、真实临时密码认证、Agno native worker和Linux父子进程，Chromium 151.0.7922.173；模型明确为SCRIPTED，未调用Go。

| 版本/范围 | 实际结果 |
| --- | --- |
| `d87d60b`，1440/390/320阅读 | 新保存的主/子回复，代码与列表语义、完整内容/缩进、键盘和触摸展开通过；实际非零退出命令与stdout/stderr分开。无横溢、页面错误或外部资源请求。 |
| 同版本，原子任务往返 | 打开原记录、后退、刷新没有新增执行POST或模型请求。 |
| 同版本，三宽实际停止 | 原父子进程分别约0.74/1.02/0.89秒后不再运行；390实际观察到中间停止状态，其他两宽直接观察到完成态。15次SCRIPTED响应合计。 |
| `5fcc4fd`，390受影响补验 | 实际stopping时按钮disabled；第二次真实触摸后仍1 POST、1 ControlCommand；原父子进程约0.956秒后不再运行，刷新不重发。另3次SCRIPTED响应。 |

最后一次修改仅停止按钮条件及相应测试；三宽阅读证据保留准确旧head，不冒称全部重跑。子进程最终观察为非运行的Z状态，不宣称已经reap；清理未额外杀任务进程。QA服务、临时数据库与工作区已清理。

UNKNOWN、危险Markdown、模型声称成功但exit7、finalizing展示另用明确FIXTURE验证，不能当作真实服务端执行证据。loopback测试代理保留浏览器取消GET产生的BrokenPipe诊断，无页面错误；没有抹掉失败日志。

## Clipboard Contract Correction

初次验收要求浏览器复制逐字包含最后一个LF，实际失败，原FAIL记录保留。独立审查用无产品样式/脚本的标准pre/code在三宽复现相同行为：DOM和Range完整，原生选择/剪贴板省略一个末尾LF。用户并未要求新增字节无损复制工具，故先明确修正自定验收契约，再重新验证：产品DOM/自身Range精确相同，实际Ctrl+C与同浏览器标准控件逐字相同，不trim或放宽任意空白。不宣称所有浏览器、系统剪贴板均已验证。

## Screenshots

均为实际浏览器PNG，画面带测试来源标签，无真实凭据或个人资料。前三张来源 `d87d60b`，停止两张来源 `5fcc4fd`。

- [桌面回复](../../../docs/images/research-readable-results/desktop-reply.png)
- [手机子助手结果](../../../docs/images/research-readable-results/mobile-child-result.png)
- [320像素命令失败](../../../docs/images/research-readable-results/narrow-command-failure.png)
- [手机等待停止](../../../docs/images/research-readable-results/mobile-stopping.png)
- [手机确认停止](../../../docs/images/research-readable-results/mobile-stopped.png)

## Traceability and Limits

云端审查目录 `/workspace/design-audit/research-readable-results-20261028`。非作者初始完整审查 `code-review/review-2a451c8.json` SHA256 `a2b9879c44a70b699a6f99aed46f9f9b174b18bc6917133f7a4a814d3383d30a`；三宽浏览器 `browser-qa/verification.json` SHA256 `85d812ac5436bad2e86e5ce39ba49b4bc5bf29434487a778e837b9fae0ceeb76`；最终停止补验 `browser-qa/stop-disabled-verification-5fcc4fd5.json` SHA256 `922a2d4a79ec6e22ca51acc9dbed5be436a9bc736591d31c0f3415071ea1a2a5`。

ui-ux-pro-max用于正文可读性、44像素触摸目标和焦点；impeccable clarify/distill用于实际状态措辞、原文按需展开和必要反馈。沿既有官方固定来源阅读，未安装技能或执行其脚本。没有新增设计系统。

未验证真实模型研究质量、GPU/SSH、Windows进程停止、操作系统级沙箱、30会话容量、物理手机或用户可访问部署。下一片为应用/我的任务/我的资源及补模型返回原研究；本片不代表全站易用性已完成。既有PR发布暂停不受此记录改变。
