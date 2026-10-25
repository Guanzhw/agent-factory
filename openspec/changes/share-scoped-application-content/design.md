# Design

## Context

动机见proposal；消费者为`restore-team-research-application`的自动研究记录与成果引用。实际源码边界：

- `ResourceSharing`保存owner与personal/team可见性；`owner()`检查读取成员和可见性，不自动检查资源owner是否仍启用。本服务补充当前owner成员检查，不新建团队目录或ACL。
- `Store.artifact(task_id, artifact_id)`返回数据库字节并核对已有sha256，但本身不检查owner；现有`FactoryAPI.download`先做`scoped_task`。发布方必须先`Store.task(task_id, owner)`，共享读取必须先检查精确发布引用，不能直接代理全job。
- `Store.artifact_identity`另开engine事务、为大checkpoint分块hash加锁，要求非空大小；它不负责权限，也不能自动加入应用领域事务。本服务读取现有受输出预算约束的普通artifact，使用`artifact`，不添加第二套hash证明链或把checkpoint端口当授权接口。
- `GovernedStorage.write/read`借用`Store._connection`，可复用`Store.transaction`；领域写入和内容快照须在同一事务完成。`_application_context.write_artifact`默认`application_output/unverified`，不能因发布而提升证据等级。
- `StorageGovernance`管理目录准入/隔离回收；数据库artifact仍由Store保存。共享不移动文件、不创建任意路径或改变证据/UNKNOWN保留约束。

## Goals / Non-Goals

**Goals:** 提供小而明确的发布/当前可见性/限定读取接口，供领域记录同事务调用；用真实PG证明授权、回滚和精确产物边界。

**Non-Goals:** 不做CMS、全文/向量检索、评论/分支权限、事件订阅、分享外部URL/任意文件、复制凭据或跨服务器代理下载。P3单独定义outbox；本变更不宣称已完成研究相关性、模型结论或远端归档验收。

## Decisions

### 不可变快照与既有可见性

新增内容表保存生成ID、owner、有限来源标签（application/record/revision）、curated JSON快照、精确产物引用和createdAt。来源标签仅用于应用关联，不是执行身份或真实性证明；core不解释项目/实验字段。应用决定哪些字段适合共享，core对有限JSON及已有敏感键/明显凭据文本规则校验；不声称正则能识别任意秘密。发布不读取vault、连接配置或完整任务详情。

发布内容不可变；领域记录更新生成新快照，应用保持自身revision/latest关系。core不另造编辑历史/并发状态机。请求幂等复用GovernedStorage命令回执；相同owner/key同内容返回原发布ID，异内容冲突。新快照默认personal，调用者必须明确传team；研究应用按已确认默认团队读策略显式选择team。为内容ID注册`content:<id>` ResourceSharing引用；作者可切回personal撤回团队读取，非作者只能读。回放旧发布回执不恢复已撤回的team状态。

### 精确产物引用与来源投影

每个产物引用只接受taskId、artifactId、sha256。发布验证当前actor拥有该task，产物属于该task，实际字节hash等于给定sha；引用必须是当前Factory已经落库的普通产物，不接受调用者的path/URL/owner/verified标记。错误归属、缺失产物或hash不符使整次发布失败。存储验证沿用已有artifact实现，预先检查普通产物输出大小上界；不接受checkpoint规模内容进此接口。

读取`/application-content/{id}/artifacts/{artifactId}`先按当前成员/ResourceSharing检查发布内容，再仅按记录内的完整元组调用Store.artifact并核对固定hash。没有列入的同task其他artifact仍不可读，更不能由publicationId获得job、私聊或连接列表。下载使用附件和`private, no-store`，不内联执行HTML。安全投影仅包含所需的原产物标识、名称、类型、大小、hash及已有证据等级/应用来源字段，不暴露执行binding清单。core生成的发布元数据标为作者发布内容，不把正文中的主张解释为core验证；原`unverified`不会被提升为科学验证。

源产物缺失或完整性不符返回明确失败，不静默改指向另一产物、不返回缓存旧字节或自动重跑研究。内容共享不等于无限保留契约；实际文件归档和保留策略仍由现有存储与应用成果流程负责。

### 最小API与事务接入

服务提供publish、read、list及set_visibility，另有精确artifact读取；HTTP身份来自现有Auth，不接受owner覆盖。list只列本人和当前可读team快照，使用有界分页；分页结果仍需逐记录当前权限检查。具体字段长度沿用当前bounded JSON/引用边界，并在API契约测试固定，不设计任意filter语言。

可信应用服务在已有领域事务内调用publish；发布表、命令回执和ResourceSharing变更必须使用同一连接。调用方提交前发生异常时领域记录与发布一起回滚，不出现仅一边成功；提交后重试返回同一发布，不重复生成快照。API处理器不接收数据库连接或作者身份委托。领域来源真假由应用业务校验，core只保证当前作者、发布内容及产物归属。

可见性切换与读取的并发语义是：撤回提交后开始的任何新读取，含旧URL/handle，都重新检查并拒绝；已经交付给用户的字节不能远程撤回，正在进行的读取不宣称具备强制抹除能力。成员禁用同样在新读/写时生效；应用不能缓存授权后绕过core。

## Risks / Trade-offs

- [作者选择了不适合共享的内容] → 应用只提交curated字段；core拒绝结构中的凭据输入并不给任何秘密解析能力，不声称可自动理解任意二进制内容的保密性。
- [引用扩大为整个任务授权] → 下载入口只接受已发布元组；测试同task未发布产物、其他owner产物、旧handle撤权及全job直接访问均失败。
- [事务接口被独立engine连接破坏] → 真实PG回滚与另一连接不可见性测试；不调用artifact_identity的独立事务充当发布事务。
- [研究解释被误当验证] → 分开作者内容与core来源元数据；输入不能覆盖owner/hash/verification字段，保留原证据等级。

## Migration Plan

只新增内容表与命令回执，复用现有共享表；默认没有任何公开内容。不迁移或自动分享旧任务、用户文件或凭据。先实现core服务与限定API及A02/A06机制测试，再由研究应用接入自动记录；回退移除路由/装配，不删除领域记录、产物或历史回执。
