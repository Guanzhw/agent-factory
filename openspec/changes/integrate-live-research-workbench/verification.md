# 稳定项目路径阶段记录

基线b2a2460；spec先行085ebab。正式工作台不import demo数据、chat或chart。当前只接稳定projects/assistants读取与目标领域变更；后续运行/轮次/团队/助手接口仍待后端冻结并继续接线，本阶段不是完整产品完成。

- `npm run check` exit0：46文件、453测试通过，0跳过，包含5个新工作台测试及11个既有目标/原请求恢复回归；lint/typecheck/default core build通过。
- `node scripts/check_web_architecture.mjs --config scripts/architecture-web.json` exit0：88模块、0violations、0coverageGaps。首次命令遗漏必需config参数，报明确配置错误，修正调用后通过；无架构规则变动。
- 初次typecheck因新JSX条件漏闭合花括号失败，修复语法后上述完整check通过。
- 真实Chromium synthetic transport：1487×1058、390×844各一条项目旅程通过，0pageerror、0consoleerror、0写入。平台→工作台→项目、修改表单/取消、证据页刷新、history、创建对话框Esc/焦点返回、窄屏助手、返回平台通过。脚本和[结果](evidence/project-browser.json)、[桌面](evidence/project-desktop.png)、[窄屏](evidence/project-mobile.png)已保留。
- 首次浏览器夹具缺少auth config必填loginPath/logoutPath，平台入口未出现，见[首失败](evidence/first-fixture-failure.txt)；补齐现有公共配置契约后通过，未修改生产认证/超时/断言。
- 运行只绑定127.0.0.1:4176，无PG、模型、GPU或外部身份。当前仍保留Vite供后续接线验证，最终由本任务清理。

后续须冻结执行/证据API并接完旅程、实际API双用户浏览器、独立精简复审与集成CI。真实模型/GPU验收仍需对应参数与环境，不由本阶段合成结果替代。
