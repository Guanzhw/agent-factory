# Proposal

## Why

研究应用需要让团队读取作者明确发布的条件、结论和证据，但当前产物下载必须通过所属任务的owner权限。不能为了共享一份证据让Bob冒充Alice或打开Alice整个job；需要core提供精确内容授权，领域选择仍由应用负责。

## What Changes

- 新增成员拥有的不可变内容发布快照：有限curated内容、应用来源引用和作者自有task的精确artifact/hash引用，不接受凭据或运行授权字段。
- 复用ResourceSharing的personal/team可见性和Auth当前成员检查，作者管理发布与撤回；团队只读指定快照及其中列明的产物。
- 通过GovernedStorage复用外层事务，让应用领域修订与发布快照同提交/回滚；不建设第二ACL、文件服务或事件平台。
- 共享读取不扩展现有job/connection API权限；保留原artifact provenance，不把发布、hash吻合或agent解释标成科学验证。

## Capabilities

### New Capabilities

- `scoped-application-content`: 作者发布、成员限定读取与当前撤权控制的应用内容和精确产物引用。

### Modified Capabilities

无；现有任务/产物读取与资源共享行为保持不变。

## Impact

历史设计起点为本地`836f810d7fc45d8a269ca1926d2b8caa35046cb0`，继承PR104 core-only验证版本；实施与独立审查基线为3ed6e26400a8109f62fd74552c1e7b9640cc3678。预期新增core内容服务/API与专属测试，接入现有ResourceSharing、Store artifact和Auth；无新依赖、研究schema、文件迁移或外部调用。当前消费者为`restore-team-research-application`的P6自动记录/成果引用，验收关联A02/A06及后续B02/C04；真实研究价值不由本契约测试代替。
