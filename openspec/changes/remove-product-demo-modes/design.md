# Design

## Context
Settings.demo 默认 true，FACTORY_MODE 默认 demo；create_app 会种 persona/material，FactoryAPI 暴露 /demo/login，CookieBridge 接受 demo cookie。development_identity 与 scripts/dev.py 提供可运行本地演示身份/数据库。前端另有原型数据与单 HTML 打包。正式 OIDC/token 桥接已有实现，应保留单一真实认证链。

## Decisions
删除可选演示运行模式，而非隐藏按钮或将其改名为开发登录。生产构造与 CLI 不接受开启合成身份的参数；旧配置值拒绝并给缺项说明。认证配置验证应早于数据库/目录/种子副作用。无浏览器 IdP 时不提供登录替身；保留已配置外部 token 接口与内部原执行身份的既有边界。

测试用成员、模型、种子和本地 OIDC 仅属于 tests/helper、测试进程或受测依赖注入；不能通过环境变量/CLI/HTTP打开，也不能被生产 wheel/部署入口导入。迁移原测试的行为断言而非批量跳过。由独立 reviewer 检查没有把 demo=True 改名留下同等旁路。

删除当前可运行 HTML/原型入口及打包器，截图和历史提交引用仍能说明旧验收但不作为推荐下载。正式构建无演示数据回退。已有 demo 数据的模式标记不被重写为 production；旧库不自动提升身份，说明需盘点与单独清理确认。

## Validation
静态/构建与 wheel 检查无 demo 登录/内置身份服务；旧参数 fail closed；新空 PG 实际启动不种用户；实际浏览器用 tests 内本地 OIDC 证明安全回跳、退出重登、平台与研究入口，另证明缺身份无登录旁路。保留首次失败，完整适用 Python/PG/Web/独立 core 检查。外部组织 IdP 未连接不写真实验收通过。

## Non-goals
不删除真实或旧 demo 数据，不访问用户电脑，不新增 IdP/密钥/grant、公开服务、模型/GPU调用，不重做 UI。
