# Design

## Context
当前Workspace的所有页面使用根路径与tab/project query。浏览器startBrowserLogin发送空JSON；server callback固定跳`/`。

## Decisions
客户端提交当前pathname/search/hash，服务端在创建flow前校验有界JSON及returnTo。目标须以`/`开头，urlsplit的path严格为`/`，无scheme/netloc/backslash/control；query/hash仅为导航，资源授权仍由原接口负责。现有1024字节body限制保留。

原flow保存returnTo；完成一次性state与身份校验后同时返回token和目标。旧flow没有目标仍返回`/`。失败仍使用静态错误地址，不反射请求目标/provider错误。不新增sessionStorage恢复状态机、不允许callback覆盖目标。

## Validation
便携ASGI测试成功返回、服务重建后的原flow、外部/编码路径/控制字符拒绝和callback注入拒绝。前端检查实际POST目标。真实浏览器使用本地synthetic OIDC验证deep-link/login/back-forward；该结果不代表生产IdP验收。core-only原研究URL仍由默认导航规范化到目录。
