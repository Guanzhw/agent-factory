## 1. Remove runtime modes
- [ ] 1.1 删除配置/认证/装配/种子与内置身份服务旁路，保留外部身份和原操作恢复边界。
- [ ] 1.2 将必要合成 fixture 迁至测试边界，更新启动脚本/部署/CI 与当前文档。
## 2. Remove frontend demos
- [ ] 2.1 删除 persona UI/API、原型运行入口/数据和 HTML 打包器，保持真实登录缺项与平台/应用导航。
## 3. Verify and review
- [ ] 3.1 静态/wheel/旧参数反例、真实 PG/测试 OIDC 浏览器、完整适用套件；保留首次失败。
- [ ] 3.2 作者外精确 base/head 完整 diff 与简洁性审查，整改复审；精确 CI 后合并并核 main。
- [ ] 3.3 报告影响、真实配置路径、旧数据只读盘点边界与本机更新步骤；不自动清空数据。

### Published checkpoint (ba08307)

Implementation/removal and incremental reviews are recorded in verification.md
and review.md. Keep 3.1/3.2 open: exact fast CI 40223992140 passed, but full CI
40223312294 at d6c8f62 failed with 36 failures/9 errors in platform PG.
The browser fixture failure was corrected and independently reviewed (8/8 real
Chromium scenarios); remaining PG fixture corrections and final full validation
are in progress. No merge or resulting-main success is claimed here.
