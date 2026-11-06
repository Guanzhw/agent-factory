# 在 Windows 启动本地服务

本指南使用 PowerShell、原生 Windows Python 和本机 PostgreSQL。完成后，你可以通过 HTTPS 登录 AutoResearch，并让助手运行本地 CPU 实验。

这些命令创建的是你自己的持久环境，不是测试夹具。已有 PostgreSQL 数据库可直接使用；不要重新初始化已有数据目录。服务只监听本机回环地址。

## 准备程序和目录

准备 Node.js 24、Python 3.12 或更高版本、uv，以及 PostgreSQL。以下示例使用 PostgreSQL 17 的工具。把路径改成你的实际安装位置和仓库位置：

```powershell
$repo = 'C:\src\agent-factory'
$pg = 'C:\Program Files\PostgreSQL\17\bin'
$localRoot = 'C:\AgentFactoryLocal'
$data = Join-Path $localRoot 'postgres-data'
Set-Location $repo
```

将持久数据放在源码目录之外，更新源码时继续保留这些数据。确认下列程序可用：

```powershell
node --version
uv --version
& "$pg\pg_ctl.exe" --version
```

安装锁定依赖并构建界面。每步成功后再继续：

```powershell
uv sync --frozen --python 3.12
if ($LASTEXITCODE) { throw 'Python 依赖安装失败' }
npm ci --ignore-scripts
if ($LASTEXITCODE) { throw '前端依赖安装失败' }
npm run build
if ($LASTEXITCODE) { throw '前端构建失败' }
```

构建成功后，仓库内应存在 `dist/index.html`。下载失败时先解决网络或包源问题；一个已创建的 `.venv` 不代表依赖已经安装完成。普通使用不需要 `browser` 测试依赖组。

## 准备 PostgreSQL

如果已有专用数据库和应用账号，跳到下一节。应用账号需要拥有应用数据库，以便创建和更新表。

如果需要新建本机实例，先确认端口 `55432` 空闲，再执行：

```powershell
if (Test-Path -LiteralPath $data) { throw '数据目录已存在，不得重新初始化' }
New-Item -ItemType Directory -Path $localRoot -Force | Out-Null
& "$pg\initdb.exe" -D $data -U local_pg_admin --auth=scram-sha-256 --encoding=UTF8 --pwprompt
if ($LASTEXITCODE) { throw '数据库初始化失败' }
& "$pg\pg_ctl.exe" -D $data -l "$localRoot\postgres.log" -o '-h 127.0.0.1 -p 55432' -w start
if ($LASTEXITCODE) { throw '数据库启动失败' }
& "$pg\createuser.exe" -h 127.0.0.1 -p 55432 -U local_pg_admin -W --pwprompt --no-superuser --no-createdb --no-createrole factory_app
if ($LASTEXITCODE) { throw '应用角色创建失败，先核对已有状态' }
& "$pg\createdb.exe" -h 127.0.0.1 -p 55432 -U local_pg_admin -W -O factory_app factory
if ($LASTEXITCODE) { throw '应用数据库创建失败' }
```

在工具提示中输入并保存管理员和应用账号密码。以上命令不注册 Windows 服务。看到数据库启动成功后再配置应用。

## 配置登录和 HTTPS

准备覆盖访问地址的 TLS 证书、对应私钥，以及至少 32 UTF-8 字节的随机 JWT 签名密钥。将密钥保存在自己的密码管理器或部署配置中。证书必须受浏览器信任；证书申请和信任配置取决于你的本机环境。

在启动应用的 PowerShell 窗口中加载配置。已有数据库用户需相应修改账号、主机、端口和库名：

```powershell
$dbCredential = Get-Credential -UserName factory_app -Message '输入数据库应用账号密码'
$dbPassword = [Uri]::EscapeDataString($dbCredential.GetNetworkCredential().Password)
$env:FACTORY_DATABASE_URL = "postgresql+psycopg://factory_app:${dbPassword}@127.0.0.1:55432/factory"
Remove-Variable dbCredential, dbPassword

$jwt = Read-Host '输入已保存的 JWT 签名密钥' -AsSecureString
$env:FACTORY_JWT_KEY = [Net.NetworkCredential]::new('', $jwt).Password
Remove-Variable jwt

$env:FACTORY_WORKSPACE = Join-Path $localRoot 'factory-workspace'
$env:FACTORY_LOCAL_LOGIN_ORIGIN = 'https://127.0.0.1:3100'
$env:FACTORY_TLS_CERT = Read-Host '输入证书文件的绝对路径'
$env:FACTORY_TLS_KEY = Read-Host '输入私钥文件的绝对路径'
```

访问主机、协议和端口必须与 `FACTORY_LOCAL_LOGIN_ORIGIN` 完全一致。签名密钥、数据库密码和证书私钥不要写入仓库或启动命令参数。

首次启动会在 `FACTORY_WORKSPACE/runtime/credential-vault.key` 创建凭据加密密钥。把该文件与数据库一起备份，并在重启时保留它。只有数据库备份无法恢复已加密的模型和工具凭据。

如果还没有本地成员，在应用停止时创建一个新成员：

```powershell
$member = Read-Host '输入新的成员 ID'
uv run agent-factory-local-user $member
if ($LASTEXITCODE) { throw '账号创建未完成，先核对实际状态' }
```

在隐藏提示中输入并确认 12–128 字符密码。该命令创建普通成员，不覆盖已有身份或重置密码。命令中断后，先核对记录，不要删除旧数据来重试。已有成员跳过此步。

## 启用本地文件与命令

需要文件工具时，创建专用研究目录并设置绝对路径：

```powershell
$researchRoot = Join-Path $localRoot 'research-workspaces'
New-Item -ItemType Directory -Path $researchRoot -Force | Out-Null
$env:FACTORY_RESEARCH_WORKSPACE_ROOT = $researchRoot
```

需要运行本机实验时，启用命令，并给出已安装工具的绝对目录：

```powershell
$env:FACTORY_RESEARCH_HOST_COMMANDS = '1'
$env:FACTORY_RESEARCH_COMMAND_PATH = (Resolve-Path '.venv\Scripts').Path
```

需要 Git 或其他 CLI 时，用分号追加它们的绝对安装目录。路径不能包含 `.`。工具直接执行命令，不做 shell 展开。项目依赖需要按研究目标准备。

这些命令使用服务账号的 Windows 权限。工作目录不是操作系统沙箱，也不会限制命令只能访问目录内的文件。只需要对话时可省略本节，只需要文件操作时可省略启用命令的两行。

## 启动并登录

在仓库根目录、同一 PowerShell 窗口中运行：

```powershell
uv run python -m uvicorn agent_factory_server.research:create_app --factory `
	--host 127.0.0.1 --port 3100 `
	--ssl-certfile "$env:FACTORY_TLS_CERT" --ssl-keyfile "$env:FACTORY_TLS_KEY" `
	--timeout-graceful-shutdown 35 --no-access-log
```

看到应用启动完成后，打开 `https://127.0.0.1:3100`，用已创建的成员登录。进入 **工作** 后，按[研究会话指南](PERSONAL_RESEARCH_SESSIONS.md)配置自己的模型并提交一个小任务。

`npm start` 和 `uv run agent-factory` 是 HTTP 启动入口，适用于已有 HTTPS 反向代理的部署；它们不能替代上述直接 HTTPS 登录命令。组织 OIDC 的装配方式见[浏览器身份契约](BROWSER_AUTH_PROCESS_ENFORCEMENT.md)。

配置保存成功不等于模型已可用。先通过一个小任务核对真实模型响应、工具退出状态和产物，再扩大任务范围。

## 停止和再次启动

先在界面请求停止正在进行的研究，等待原任务停止回执。然后在应用终端按 Ctrl+C，等待应用退出，再停止你在本指南中启动的 PostgreSQL：

```powershell
& "$pg\pg_ctl.exe" -D $data -m fast -w stop
if ($LASTEXITCODE) { throw '数据库停止未确认，请核对原实例' }
```

HTTP 连接排空最多等待 35 秒，之后应用有独立的 35 秒清理预算。两阶段合计可能接近 70 秒。排空超时不代表任务成功或研究进程已经停止；根据[关闭说明](SHUTDOWN.md)核对实际结果。

再次使用时，加载原来的目录、签名密钥、数据库和证书配置，启动原数据库，再执行 HTTPS 应用命令：

```powershell
& "$pg\pg_ctl.exe" -D $data -l "$localRoot\postgres.log" -o '-h 127.0.0.1 -p 55432' -w start
if ($LASTEXITCODE) { throw '数据库启动失败' }
```

不要再次执行 `initdb`，也不要重新创建同名数据库或成员。保留数据库、应用 workspace、凭据加密密钥和研究文件。测试验收程序会销毁临时数据库，不是持久服务启动器。
