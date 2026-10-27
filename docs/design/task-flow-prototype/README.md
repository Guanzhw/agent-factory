# Agent Factory 任务流程原型

这是独立交互设计产物，全部为明确标注的示例数据。它没有接入正式系统，不模拟登录，不连接模型、远程主机或后端，不执行真实任务。请勿输入真实资料或凭据。

主导航为 **应用 / 我的任务 / 我的资源**。建议依次试三条路径：

1. **研究项目补资源**：应用 → AutoResearch → 选择或新增示例模型 → 保存并回到原项目 → 核对配置、约定和启动动作。示例 API 地址使用 `https://model.example.invalid/v1`。
2. **从模板创建任务**：应用 → 浏览任务模板 → 用此模板创建任务 → 填目标 → 生成提案 → 接受方案 → 明确开始。模板作者的编辑、保存、发布是独立路径；远端方案不能定时。
3. **处理原任务的问题**：我的任务 → 需要回答、失败或运行中样例 → 从当前问题继续。核对原请求、补配资源、停止请求与最终停止分别呈现；暂停计划只影响未来触发。

## Windows PowerShell：在新目录查看

需要已有 Git 和 Python 3。以下命令创建独立目录，不修改已有仓库或文件；不需要 Node、npm、数据库或账号：

```powershell
$prototypeDir = Join-Path (Get-Location) ("agent-factory-prototype-" + [guid]::NewGuid().ToString("N"))
git clone --depth 1 --single-branch --branch design/task-flow-prototype-20261027 https://github.com/Guanzhw/agent-factory.git $prototypeDir
if ($LASTEXITCODE -ne 0) { throw "下载失败，请保留原目录并查看 Git 提示。" }
Set-Location (Join-Path $prototypeDir "docs/design/task-flow-prototype")
Get-FileHash .\index.html -Algorithm SHA256
py -3 -m http.server 8765 --bind 127.0.0.1
```

看到服务启动提示后，在这台电脑的浏览器打开 <http://127.0.0.1:8765/>。命令窗口保持开启，用 `Ctrl+C` 停止。若已安装的 Python 命令是 `python`，可将最后一行的 `py -3` 换成 `python`。若端口被占用，将命令和地址中的 `8765` 一起改为一个空闲端口。

也可从 GitHub 下载本目录的 `index.html`，单独放入一个新文件夹，再于该文件夹运行上面的 HTTP 命令。只需这个 HTML 文件，所有样式、图标和交互均已内嵌。

## 版本与验证边界

HTML SHA256：`3e0b5c496aa9f21cc9b8ca0224796e99d484fdf2b4b0adfc17a0d51e4f68617e`。

作者与非作者已在云端 Chromium 的本地 HTTP 环境实际操作桌面和手机宽度三流程；非作者复查了双击不会跨越发布、接受或启动边界，未发现 JS 错误或外部请求。该结论只允许交用户试用原型，不代表真实团队易用性、后端执行或完整无障碍验收。

Windows 尚未实测。云端 `file://` 被浏览器环境策略拒绝，未绕过或重试，所以不承诺双击 HTML 直接打开的兼容性。上述 HTTP 启动方式已在 Linux 验证，仅绑定本机地址。

模型/GPU/SSH、真实权限、真实保存和任务执行、研究续接均未验证；维护次级页只说明范围。本分支没有接入产品入口、修改认证协议或增加生产 demo 模式，不应合并作为正式 UI 上线。

交互设计使用了 ui-ux-pro-max 的就地错误、状态保持和渐进展开原则，以及 Impeccable clarify/distill/operate 的术语澄清、步骤精简和操作反馈指导；读取官方说明，未安装或运行其脚本。
