# 离线交付验收

- ZIP：`/workspace/agent-factory-design-reference/research-workbench-demo.zip`，264769 bytes；SHA256 `812af225718475da8c7fa5d6ddc31f056e245644612fab7fc5193c7d0c6b90db`。
- 页面构建来源：`2fbc24ca7bb4cc7703a4a2f5c7884f326f0442b2`。包内两份 JS/CSS 与冻结构建逐字节一致；仅 HTML 的相对路径和 fixture 注入改变。
- ZIP仅7文件：HTML、两份assets、fixture、README、LICENSES、BUILD。无源码仓库、node_modules、秘密。
- `python3 scripts/package_research_demo.py --build /tmp/af-research-demo-dist --source-head 2fbc24ca7bb4cc7703a4a2f5c7884f326f0442b2 --output /workspace/agent-factory-design-reference/research-workbench-demo.zip`：exit 0。
- ZIP解压后 `python3 -m http.server 8765 --bind 127.0.0.1 --directory /tmp/af-research-offline-unpacked`，未使用生产服务或PG。
- `PLAYWRIGHT_BROWSERS_PATH=/workspace/.cache/ms-playwright /workspace/agent-factory-core-only/.venv/bin/python scripts/accept_research_demo_browser.py --offline-package --origin http://127.0.0.1:8765 --output /tmp/af-research-offline-final`：exit 0；1487×1058 与 390×844 两旅程通过，0跳过。
- 无 Playwright API 拦截。平台→应用→项目/页签/对话框→返回、资源/模型/连接上下文、浏览历史/刷新、新建空项目、退出/Alice→Bob隔离通过。未知API本地404，外部URL本地拒绝；实际网络只含本机静态HTML/JS/CSS。consoleErrors/pageErrors均空。
- [完整网络及结果](offline-browser.json)、[桌面](offline-workbench-desktop.png)、[窄屏](offline-workbench-mobile.png)。
- Ruff两脚本通过；OpenSpec严格验证通过。
- 已停止本次8765静态服务及此前4175 Vite服务；未删除证据/构建。

仅合成前端交互，不代表真实登录、模型/GPU执行或最终产品验收。Windows启动命令已提供但本次浏览器运行环境为Linux，未在Windows实跑。正式UI仍待用户体验确认。

## 无安装单 HTML

- `research-workbench-demo.html`：862949 bytes，SHA256 `e2f484dfb9bcd42baad31882f27488273aa71b316f76ada4dd72ea9363879fbc`。直接用现代 Chrome/Edge 打开，无服务器/依赖。
- 同一打包命令追加 `--html-output /workspace/agent-factory-design-reference/research-workbench-demo.html`。JS/CSS与fixture直接内联，无第二页面实现；完整许可证与构建出处保留为inert JSON并核对与ZIP许可内容相等。
- 真实 `file://` Chromium desktop/mobile 运行同一 `--offline-package` 验收，exit0、2旅程通过、零跳过。平台入口/项目/图表与证据交互/输入/返回/刷新/退出重登及Bob隔离均通过；网络只有本HTML及query，无HTTP/API/外部asset请求，console/pageerror空。见[file-browser.json](file-browser.json)、[平台](file-platform-desktop.png)、[桌面](file-workbench-desktop.png)、[窄屏](file-workbench-mobile.png)。
- 首次file模式浏览器启动在默认sandbox以 `sandbox_host_linux.cc:41 shutdown: Operation not permitted` 失败（页面尚未载入）；按原本获准的浏览器执行权限启动后验证成功，无浏览器安全参数修改或断言放宽。
- 单HTML实测仍为LinuxChromium；Windows/其他浏览器未实跑。file存储受浏览器策略限制，若不能保留演示状态，可用ZIP的回环静态服务备用。
