import type { PersonalOrxProjectReviewSummary, PlanReview } from './models.js';

export function projectCreationSummary(review: PlanReview): PersonalOrxProjectReviewSummary | undefined {
  const value = review.planSummary?.projectCreation;
  const project = value?.project; const effects = value?.effects; const billing = value?.billing;
  if (!value || value.schema !== 'native-orx-project-review-v1' || !value.requestId || !/^[a-f0-9]{64}$/.test(value.previewHash)
    || !project || typeof project.name !== 'string' || !project.name || typeof project.path !== 'string' || !project.path
    || !['empty', 'existing', 'clone', 'paper'].includes(project.source)
    || !(project.cloneUrl === null || typeof project.cloneUrl === 'string') || !(project.paperId === null || typeof project.paperId === 'string')
    || !effects || effects.version !== 'native-orx-create-consent-v2' || effects.remotePath !== project.path || effects.repository !== project.cloneUrl || effects.paperId !== project.paperId
    || effects.clone !== (project.source === 'clone') || effects.paperDownload !== (project.source === 'paper') || typeof effects.gitInitialization !== 'boolean'
    || (project.source === 'clone') !== !!project.cloneUrl || (project.source === 'paper') !== !!project.paperId
    || effects.remoteWrites !== (effects.clone ? 'clone-into-new-or-existing-empty-folder-and-project' : project.source === 'existing' ? 'register-existing-folder' : 'create-new-folder-and-project')
    || effects.pathResolution !== (effects.clone ? 'upstream-clone-target-symlinks-followed-no-new-folder-guarantee' : 'upstream-canonical-path-and-enclosing-git-root')
    || effects.githubSyncEnabled !== false || effects.automaticExperiment !== false || effects.hardBudgetEnforced !== false || effects.billing !== 'owner-remote-account-possible-cost'
    || JSON.stringify(effects.modelInput) !== JSON.stringify(['README', 'selected-code', 'file-list', 'paper-summary'])
    || effects.starterSuggestions !== 'may-request-four-project-chat-suggestions' || effects.modelSelection !== 'remote-preferred-or-ready-harness'
    || effects.emptyCacheHitOrNoHarness !== 'may-skip-model-request' || effects.unknownResponse !== 'read-only-reconcile-never-resend'
    || !billing || billing.controllerLedgerScope !== 'local-controller-only' || billing.remoteUsageStatus !== 'unknown' || billing.remoteCostStatus !== 'unknown'
    || billing.remoteBilling !== 'owner-remote-account-possible-cost' || billing.remoteCostIncludedInUsageBudget !== false || billing.hardRemoteBudgetEnforced !== false || value.ownerConsentSeparate !== true) return undefined;
  return value;
}

export const needsProjectCreationSummary = (review: PlanReview) => review.planSummary?.application === 'personal-orx-project-create-v1' || review.planSummary?.projectCreation !== undefined;

export function ProjectCreationReview({ value }: { value: PersonalOrxProjectReviewSummary }) {
  const p = value.project; const e = value.effects;
  return <section className="personal-command-summary" aria-label="固定项目创建输入"><h3>此次固定项目创建范围</h3>
    <dl className="plan-details"><dt>项目名称</dt><dd>{p.name}</dd><dt>远端目标绝对路径</dt><dd>{p.path}</dd><dt>项目来源</dt><dd>{({ empty: '新建空目录', existing: '已有远端目录', clone: '公开 GitHub 仓库', paper: 'arXiv 论文' })[p.source]}</dd><dt>公开仓库</dt><dd>{p.cloneUrl ?? '未指定'}</dd><dt>论文 ID</dt><dd>{p.paperId ?? '未指定'}</dd></dl>
    <p>{e.clone ? '将 clone 到新目录或已有空目录并登记项目；已有空目录可能被修改。目标及父目录的符号链接会指向实际写入位置，Factory 未检查或锁定远端路径。' : p.source === 'existing' ? '登记已有目录，按上游规则解析到所在 Git 仓库根目录及符号链接的实际位置。' : '在远端新建目录并登记项目。'}{e.paperDownload && '将下载论文 PDF。'}{e.gitInitialization && '将在该目录初始化 Git。'}</p>
    <p>GitHub 自动同步关闭，不自动开展实验。上游可能生成 4 条项目建议，将 README、部分代码、文件清单或论文摘要发送给远端偏好或可用 harness 的模型。空项目、缓存命中或无可用 harness 时可能跳过模型请求。</p>
    <p className="policy-note">请核对此次固定创建范围。拥有者确认后才会提交远端副作用。</p>
    <details className="technical-detail"><summary>固定创建请求及副作用技术快照</summary><span>原请求 {value.requestId}</span><span>预览摘要 {value.previewHash}</span><pre>{JSON.stringify(value, null, 2)}</pre></details>
  </section>;
}
