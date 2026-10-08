# Linux 开发模拟登录

这是可运行的 **DEVELOPMENT MOCK** 登录入口，供开发与合成流程验收使用。
用户已选择 Linux；真实统一登录服务目前不接入，不阻塞开发。
本入口不代表真实 IdP、生产身份、科研模型或目标机容量验收。

## 启动

使用已安装仓库依赖的环境，准备一个**已存在、独立的开发 PostgreSQL 数据库**。
启动器会在该数据库中初始化应用表；不要指向生产数据库。它不创建数据库、
安装 PostgreSQL、启动付费模型或自动分配云资源。

在当前进程环境提供 `FACTORY_DATABASE_URL`，然后执行：

```sh
.venv/bin/python scripts/run_development_factory.py \
  --public-origin https://127.0.0.1:3443 \
  --workspace /operator/path/agent-factory-development
```

也可显式传入 `--database-url`；不要把真实连接字符串提交到仓库或验收产物。
`--public-origin` 和 `--workspace` 必须明确提供。origin 必须是带端口的 HTTPS
loopback 地址，例如 `127.0.0.1`、`localhost` 或 `[::1]`，不接受外网监听地址。

启动时输出明确的 DEVELOPMENT MOCK 标签及 Base URL，不输出数据库凭据。
服务使用单 worker 和明确的开发 `admin-review` 临时计划策略。这是开发配置，
不替代生产策略选择。现有 research 素材、原生审批、权限检查和任务流程继续使用
正常 Factory 实现。

## 使用

1. 打开启动器打印的 HTTPS Base URL。
2. 临时自签证书会触发浏览器证书提示；仅对这一已确认的 loopback 开发页面继续。
   不需要把证书加入系统 trust store，也不要关闭整个浏览器或机器的 TLS 校验。
3. 点击应用登录按钮，在“开发模拟登录”页面选择 Alice、Bob、Manager 或第二位
   Manager/reviewer。身份选择绑定当前浏览器 flow，不使用共享的全局角色选择。
4. 使用正常应用导航、审批和退出登录按钮。Alice/Bob 为开发用户，两位 manager
   是独立合成管理身份，适用于双人审核；不会创建真实公司用户或外部 IdP 账号。

模拟 IdP 仍走 authorization code、PKCE S256、state、nonce 和原有严格 ID token
验证。token 兑换通过内存 ASGI transport，不发送 IdP 网络请求。应用继续使用
原有数据库中的 opaque session、当前用户权限检查、CSRF 和可撤销 logout。
没有新增竞争的 session 机制，也不向 JavaScript 返回 native JWT。

## 生命周期与限制

OIDC RSA 密钥只存在当前进程内存。HTTPS 私钥和证书仅在临时目录中以 `0600`
文件保存，目录权限为 `0700`；正常停止或异常退出上下文时删除。不会修改系统
trust、网络设置或持久化登录凭据。强制杀进程/机器断电不保证 Python cleanup
执行；临时文件仍保持私有权限，应由该开发环境的常规临时目录清理负责。

Ctrl-C 停止服务。开发数据库和 workspace 中的应用数据由操作者管理，不自动
删除。每次启动重新生成 IdP 密钥和配置指纹，因此旧浏览器会话需要重新登录。
临时 TLS 证书有效期两小时，长期开发会话需要重启这一开发服务。

`development_mock_login` 只允许与 `demo=True` 同时使用；生产配置必须拒绝它。
本启动器不接受 production 模式、真实 IdP 连接或执行 Go/科研 provider 的选项。
真实统一登录接口以后通过既有 production OIDC 配置独立接入和验收。

## 浏览器验收

浏览器验收脚本可使用启动器打印的 Base URL，例如
`scripts/accept_app_recovery_browser.py --base-url https://127.0.0.1:3443 --output-dir <private-output>`。
只运行已有授权的合成场景；TLS 忽略仅限该脚本的 loopback 测试 context。
启动器和轻量测试本身不运行这些浏览器任务、PostgreSQL 重型测试或真实外部模型。
