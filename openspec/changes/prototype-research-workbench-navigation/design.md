# Design

## Context

动机见proposal。基线f25c899，独立worktree `/workspace/agent-factory-research-ui-demo`。参考文件 `/workspace/agent-factory-design-reference/research-workbench.png` 已实际查看，1487×1058。Product Design用户上下文预检无保存记录；以本次明确选图为依据。

当前平台入口 `web/composition.tsx` 的installedApplications为空；`ApplicationCatalog.tsx`显示独立应用目录。`research-composition.tsx`显式注册research与project query，`Workspace`（App.tsx）统一管理pushState/popstate，`workspaceNavigation.ts`过滤合法tab、routePointer和query。Vite默认core；research mode显式更换entry。

认证已知缺口：`web/browserAuth.ts:startBrowserLogin` POST空body；`platform/agent_factory/browser_auth.py:272`成功callback固定跳转`/`。原地demo login保留URL不证明SSO回跳。通用return修复由独立core变更处理，本demo不改browserAuth或后端auth，不存token，不新增认证controller。

## Goals / Non-Goals

**Goals:** 用可点击synthetic状态验证选图信息结构和平台/应用边界，覆盖入口、完整返回链、直接URL、历史导航、窄屏与焦点。

**Non-Goals:** 不替换正式研究页面、不连接真实研究执行或分享、不创建第二router/执行器，不修改生产身份配置。正式UI合并需要用户体验确认；功能验收与视觉批准分开。

## Decisions

### 装配与宿主slot

新增独立demo entry/composition，仅显式demo mode安装演示应用。平台默认入口不变。Workspace增加可选 `applicationView(context): ReactNode | undefined`，在所有既有hooks之后求值；返回undefined使用原平台壳，只有research tab返回独立应用壳。比复制Workspace的身份/刷新/router更小；也避免参考图外再套一圈平台侧栏。

应用使用现有WorkspaceContext的user/navigate和显式logout回调，不自行fetch session。平台AutoResearch入口总是清空project和应用页签；研究侧始终可返回平台。资源入口进入平台资源页并有明确返回研究入口；研究内没有凭据编辑器。

| 地址 | 可见内容 |
| --- | --- |
| `/?tab=catalog` | 独立平台主页/应用目录 |
| `/?tab=research` | 研究工作台，参考图的项目概览与选中预览 |
| `/?tab=research&project=<id>` | 项目详情，有返回工作台和返回平台 |
| `/?tab=research&researchView=team` | 团队经验 |
| `/?tab=research&project=<id>&researchTab=experiments`（或evidence） | 项目实验/证据页签 |

应用query通过navigation.queryKeys/readQuery显式白名单，project仍用routePointer。未知demo项目显示「未找到演示项目」与返回入口，不能误展示第一个项目。默认core不注册research，按现有通用规则回catalog。

### 视觉测量与素材

| 区域 | 参考图测量与实现目标 |
| --- | --- |
| 应用左栏 | x0–243，约243px；品牌区高90，导航行约46，底部成员区约133 |
| 内容区 | x243–1023，约780px；内边距24–28；标题约36px/700，副标题20；主CTA约152×46 |
| 项目表 | x266 y150 w733 h233；表头52，数据行60；选中浅蓝，状态点配文字 |
| 选中项目卡 | x266 y406 w733；内边距20；标题26，正文16；页签44高 |
| 指标卡 | x287 y582 w691；图表为合成数据，蓝/紫两条线，轴与图例必须可辨 |
| 助手栏 | x1023起约464px；24px边距；header约110；消息卡圆角18；底部输入约430×138 |

字体采用已有中文系统栈并优先Noto Sans CJK SC（开放字体，若打包保留[SIL许可](https://github.com/googlefonts/noto-cjk/blob/main/Sans/LICENSE)），不在运行时请求外部字体。图标选择[Tabler官方MIT图标](https://tabler.io/icons)，24px/2px线宽接近参考；品牌与助手标识用库图标，不手绘SVG或用emoji替代。参考无照片/背景插画；图表由图表库根据明确synthetic数值渲染，不用截图冒充可交互指标。不生成无关装饰资产。

整体浅灰白背景、深墨文字、蓝色主按钮/当前导航；不引入新全站设计系统。≤1100px收窄左栏并把助手变可打开的面板；≤700px改上方紧凑导航、单列内容，助手面板独立可关闭，不让表格压缩到遮挡标题。键盘焦点可见，dialog原生焦点管理/关闭返回。

### 演示状态与交互

应用局部状态持有固定三个合成项目、项目选择/页签、新建约定草稿、演示对话和引用打开状态；需要刷新保留的演示数据只按当前owner隔离存储，不保存秘密。已有静态项目URL可刷新；新建项目也须在本浏览器会话刷新后可定位。只在明确demo入口加载fixture，正式researchApi保持不变。

新建项目表单、项目列表、实验与证据页签、团队记录打开/过滤、助手输入/发送、引用打开、头像菜单与返回路径均产生可见反馈。附件控件只选择本地文件名并明确「未上传」；不读取真实内容或发送。下一步按钮打开演示研究约定/动作确认，不能声称真实训练启动。空输入发送禁用，取消弹层不产生项目。

## Risks / Trade-offs

- [SSO深链当前未实现] → 独立core修复后集成；demo login证据与真实协议/身份分别记录，缺依赖不记通过。
- [参考图只给工作台] → 详情/团队/窄屏延续同一组件尺度，以最少必要状态补全旅程，不扩展未确认业务。
- [素材网格样式曾遮挡真实点击] → 全部demo CSS限定应用class；真实Playwright正常点击，不用force绕过。
- [技能的cloud browser/Sites在本执行环境不可用] → 仅依用户授权做现有云端受控Chromium验证；不新增公网服务。报告实际截图来源，不声称Work Mode cloud-browser预览已打开。
- [Product Design公共critical-overrides引用当前provider读取失败] → 已读image-to-code/index/user-context；在交付前补齐design-qa准则，任何未完成视觉比较保持blocked，不用静态成功冒充。

## Migration Plan

独立spec提交后实现demo；不接入默认生产entry。回退删除demo装配选择即可，原core与研究数据不变。先本地审查/真实浏览器与视觉QA，再让用户体验确认；无push/merge或正式部署。

## 独立离线交付包

已审查的 demo 构建 JS/CSS 原样打包；仅复制的 HTML 使用相对 assets 路径并先载入交付专用 synthetic fetch fixture。fixture 不进入生产 composition，不使用生产身份或凭据：默认 Alice，退出可选择 Alice/Bob，tab sessionStorage 仅保存公开演示 persona。已知只读 API 返回固定空资源，只有演示登录/退出改变 persona；未知路径、方法和外部 URL 本地拒绝，绝不转发网络。包用标准 Python 静态服务器在 127.0.0.1 打开，无 npm/Node 或额外 Python 依赖。它不是公开预览、真实身份/模型/GPU验收或正式 UI 批准。

验收从 ZIP 重新解压启动，不拦截 API：平台首页→应用→项目→返回、资源上下文、刷新、退出/Bob隔离均成功；捕获实际网络、console 与 pageerror；未知请求不产生网络。保留截图及构建来源。结束停止本次静态服务器。

单 HTML 交付使用相同冻结 JS/CSS 内联及同一 fixture；无新增页面实现。许可证与构建出处以 inert JSON 保留。file:// 模式必须实际验证 History/query、刷新与演示 sessionStorage；若浏览器不支持，以本机 ZIP 静态服务备用，不为包装修改产品路由。
