# 稳定项目路径阶段记录

基线b2a2460；spec先行085ebab。正式工作台不import demo数据、chat或chart。当前只接稳定projects/assistants读取与目标领域变更；后续运行/轮次/团队/助手接口仍待后端冻结并继续接线，本阶段不是完整产品完成。

- `npm run check` exit0：46文件、453测试通过，0跳过，包含5个新工作台测试及11个既有目标/原请求恢复回归；lint/typecheck/default core build通过。
- `node scripts/check_web_architecture.mjs --config scripts/architecture-web.json` exit0：88模块、0violations、0coverageGaps。首次命令遗漏必需config参数，报明确配置错误，修正调用后通过；无架构规则变动。
- 初次typecheck因新JSX条件漏闭合花括号失败，修复语法后上述完整check通过。
- 真实Chromium synthetic transport：1487×1058、390×844各一条项目旅程通过，0pageerror、0consoleerror、0写入。平台→工作台→项目、修改表单/取消、证据页刷新、history、创建对话框Esc/焦点返回、窄屏助手、返回平台通过。脚本和[结果](evidence/project-browser.json)、[桌面](evidence/project-desktop.png)、[窄屏](evidence/project-mobile.png)已保留。
- 首次浏览器夹具缺少auth config必填loginPath/logoutPath，平台入口未出现，见[首失败](evidence/first-fixture-failure.txt)；补齐现有公共配置契约后通过，未修改生产认证/超时/断言。
- 运行只绑定127.0.0.1:4176，无PG、模型、GPU或外部身份。当前仍保留Vite供后续接线验证，最终由本任务清理。

后续须冻结执行/证据API并接完旅程、实际API双用户浏览器、独立精简复审与集成CI。真实模型/GPU验收仍需对应参数与环境，不由本阶段合成结果替代。

## 轮次与执行配置接线

- 后端契约来源bb999e5（独立后端分支，未据此前端合成结果认定其真实恢复通过）。真实start/experiments客户端、nullable轮次/原操作、agent分析/来源、core任务入口已接；目标配置选择实际已发布应用、mode、允许材料pin与现连接，不收JSON或秘密。
- 原11项项目/请求恢复回归已迁移到正式ResearchWorkbench，原无消费者P4视图与research.css已删除；公开入口只re-export正式工作台，共用原命令恢复hook。没有保留第二执行/恢复实现。
- 最新针对性：5文件27项通过、0跳过，包括原11项、start408同键、UNKNOWN/无决策不冒充达标、执行配置空目录与精确pin/预算、demo/live共同导航回归。
- 变更后的首次完整Web：48文件中47通过、1失败；458项中457通过、1失败。失败为未修改的department-publication-ui.test.ts:67中发布材料通知等待超时，原日志[保留](evidence/full-web-first-failure.txt)。随后单独运行该文件25项通过，见[记录](evidence/publication-targeted.txt)。只证明隔离复验通过，尚未查明共享负载或fixture时序根因，不能把该完整run记为通过；未放宽超时/断言，未无改动整套追绿。
- 当前lint/typecheck、独立research build通过；架构93模块0违规/0gap。新依赖为0，未改变冻结lock。
- 最新真实Chromium两视口再次通过，增加项目→资源→模型→连接→模型→原项目/证据页返回；配置空目录实际显示缺项入口；轮次未决数据明确不作科学结论。仍是synthetic API transport，没有付费模型/GPU执行。
- 窄setup接口由并行任务提供；P7团队/QA尚待后端HTTP，仍需继续接线。当前不可合并成最终完整产品。
