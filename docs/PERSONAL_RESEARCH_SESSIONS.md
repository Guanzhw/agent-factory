# 个人研究会话

此入口属于显式 Auto Research 装配。默认 `agent-factory` 仍只启动底座；旧项目、七步研究流程和 QA 保留。自主会话复用 Agno **3.1.0** 的 Agent 工具循环，每次继续产生一个原任务，个人助手和研究会话保持不变。它不会自动从历史任务重放操作。

## 启动条件

先按 [README 的身份验证启动步骤](../README.md#start-with-configured-authentication) 完成现有 PostgreSQL、身份验证及凭据存储配置，并准备浏览器信任的 HTTPS 证书。已有账号可直接使用，不必重新创建。成员在“我的资源”配置自己的模型连接，再进入 Auto Research 的“研究会话”。本入口没有默认账号、模型或凭据。

Linux/POSIX 部署可显式选择本地研究工作目录。目录必须事先存在、为绝对路径，且路径中不能有符号链接：

```sh
export FACTORY_RESEARCH_WORKSPACE_ROOT=/absolute/owned/research-workspaces
export FACTORY_RESEARCH_HOST_COMMANDS=1
# 可选：仅覆盖可执行文件查找路径；默认使用 OS 标准路径，不继承服务 PATH。
export FACTORY_RESEARCH_COMMAND_PATH=/usr/bin:/bin
npm run build:research
export FACTORY_LOCAL_LOGIN_ORIGIN=https://127.0.0.1:3100
uv run python -m uvicorn agent_factory_server.research:create_app --factory \
  --host 127.0.0.1 --port 3100 \
  --ssl-certfile "$FACTORY_TLS_CERT" --ssl-keyfile "$FACTORY_TLS_KEY" --no-access-log
```

打开 `https://127.0.0.1:3100`。证书路径、数据库和签名配置沿用现有安全配置，不能直接把 HTTP 测试服务当作用户部署。`agent-factory-research` 的 HTTP 入口只适用于已经配置 HTTPS 终止代理的环境；上面的 Uvicorn factory 同样读取研究工具配置。

这些参数只启用受控本地工具，不创建 OS 沙箱。命令使用部署进程的 OS 用户权限，仍可能访问该用户可读的其他文件或网络；不能把 cwd、目录校验或清理环境变量当作跨租户隔离。请仅在符合团队信任边界的独立执行环境中启用，不要在有额外敏感文件的服务账户下直接开放任意命令。未配置时界面报告缺项，不默认使用服务源码目录。当前不提供自动依赖安装，也未证明 Windows 本地命令或远程个人 GPU 接入可用。

## 使用与恢复边界

- 创建时填写目标、自然语言停止边界和模型；工具次数、单操作时限是另外的机器限制。费用/token 不计量，未实现 CPU/内存/PID 硬上限。
- 运行中补充先保存，下一次模型请求才纳入。正在执行的命令不会因补充指令立即改变；“已纳入请求”不表示模型已经遵守。
- 停止先返回请求已接收。只有原受控进程组确认结束，界面才可确认本地停止；无法确认的操作保留待核对。
- 刷新或重启后打开原会话不会创建新任务。原请求无回执、未知副作用，以及重试时无法确认原工具历史的操作都不能被新一轮绕过。已确认结束且没有未解决操作的会话可显式继续。
- 历史持久保留，首片上下文容量为 12,000 字符，达到上限会拒绝新一轮。当前不自动摘要，也不把研究会话当作个人长期记忆库。
- 共享证据只能来自现有明确发布的研究内容。撤销后，新读取和依赖该来源的后续模型上下文都会停止；已经发出的模型请求不能被撤回。

验收记录须区分真实模型、真实临时文件/进程、数据库协议 fixture 和浏览器。目标 64GB/30 活跃会话容量、真实 GPU/SSH、完整隔离和研究质量均需要各自的后续证据。
