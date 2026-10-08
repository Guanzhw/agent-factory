import { useEffect, useState } from 'react';
import { api, ApiError } from './api.js';
import { PlanReviewGate } from './PlanReviews.js';
import { UsageCommitmentSummary } from './UsageLedger.js';
import { usageCommitment } from './usageLedgerState.js';
import { checkedAuthorization } from './planReviewState.js';
import { openresearchApi, type ResearchProject, type ManagedProfile, type ManagedResearchSession } from './openresearchApi.js';

type Mutation = (work: (requestId: string) => Promise<void>) => Promise<void>;
type Read = (work: () => Promise<void>) => Promise<void>;
export function ManagedNativeProbe({ project, disabled, mutate, onSession }: { project: ResearchProject; disabled: boolean; mutate: Mutation; onSession: (session: ManagedResearchSession) => void }) {
  const [profiles, setProfiles] = useState<ManagedProfile[]>([]); const [ready, setReady] = useState(false);
  const [selected, select] = useState(''); const [goal, setGoal] = useState(''); const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState('');
  useEffect(() => {
    const ctrl = new AbortController(); setReady(false); select(''); setProfiles([]);
    void openresearchApi.managedProfiles(project.id, ctrl.signal).then(value => { if (!ctrl.signal.aborted) { setProfiles(value); setReady(true); setError(''); } }).catch(() => { if (!ctrl.signal.aborted) setError('受管连接验证配置暂时无法核对；不会安装或替换配置。'); });
    return () => ctrl.abort();
  }, [project.id, refresh]);
  const profile = profiles.find(p => p.id === selected);
  return <details className="technical-detail"><summary>受管连接验证 / 单轮文本探测（高级）</summary><h3>验证已安装的原生连接</h3><p>仅允许原会话的一轮文本、最多一次提供商请求，原生工具禁用。此步骤不是完整研究流程；多步科学研究与工具循环仍不可用。</p>
    {error && <p role="alert" className="error-message">{error}</p>}
    {!ready ? <p className="quiet">正在读取已安装验证配置。</p> : !profiles.length ? <p className="policy-note">没有匹配原项目的已安装受管配置。需要受管执行绑定、独立监管与预算能力；页面不会虚构安装。</p> : <><label>已安装验证配置<select aria-label="已安装验证配置" value={selected} disabled={disabled} onChange={e => select(e.target.value)}><option value="">选择配置</option>{profiles.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>{profile && <dl className="plan-details"><dt>原生项目</dt><dd>{project.upstreamProjectId}</dd><dt>原生会话</dt><dd>{profile.upstreamSessionId}</dd><dt>原生配置</dt><dd>{profile.nativeProfileId}</dd><dt>Harness / 模型</dt><dd>{profile.profile.harness} / {profile.profile.model}</dd><dt>配置上限</dt><dd>一轮文本 · 一次提供商请求 · 原生工具禁用</dd><dt>集成验证</dt><dd>实时端到端尚未验证</dd></dl>}<label>文本探测目标<textarea aria-label="文本探测目标" maxLength={2000} value={goal} disabled={disabled} onChange={e => setGoal(e.target.value)}/></label><p className="quiet">准备只保存不可变方案，不执行模型或分配计算资源。确认预算与方案审查后，仍需另行点击执行。</p><button className="secondary" disabled={disabled || !ready || !profile || goal.trim().length < 2} onClick={() => void mutate(async id => { const session = await openresearchApi.prepareManaged(project.id, selected, goal.trim(), id); if (session.upstreamSessionId !== profile?.upstreamSessionId || session.nativeProfileId !== profile?.nativeProfileId) throw new ApiError('原生会话不匹配', 200, 'INVALID_RESPONSE'); onSession(session); })}>准备单轮连接验证方案</button></>}
    <button className="text-button" disabled={disabled} onClick={() => setRefresh(n => n + 1)}>刷新已安装验证配置</button>
  </details>;
}

export function ManagedProbeAdmission({ ownerId, project, session, disabled, busy, mutate, read, onSession }: { ownerId: string; project: ResearchProject; session: ManagedResearchSession; disabled: boolean; busy: boolean; mutate: Mutation; read: Read; onSession: (session: ManagedResearchSession) => void }) {
  const [allowed, setAllowed] = useState(false);
  const attachment = session.plan.inputValues?.managedAttachment;
  const identity = !!attachment && typeof attachment === 'object' && !Array.isArray(attachment)
    && attachment.ownerId === ownerId && attachment.connectionRef === project.connectionRefs.workspace
    && attachment.projectId === project.upstreamProjectId && attachment.sessionId === session.upstreamSessionId
    && attachment.projectIdentityHash === project.nativeProject?.projectIdentityHash;
  const profile = attachment && typeof attachment === 'object' && !Array.isArray(attachment) && attachment.profile && typeof attachment.profile === 'object' && !Array.isArray(attachment.profile) ? attachment.profile : undefined;
  const budget = usageCommitment(session.plan.usageBudget);
  return <section aria-label="受管文本探测准入"><p className="policy-note">受管连接验证记录；一轮文本、一次提供商请求、无原生工具。完成探测不代表完成科学研究。</p><dl className="plan-details"><dt>原生会话</dt><dd>{session.upstreamSessionId}</dd><dt>受管配置</dt><dd>{session.managedProfileId}</dd><dt>原生配置</dt><dd>{session.nativeProfileId ?? '原生配置标识未提供'}</dd><dt>固定 Harness / 模型</dt><dd>{profile ? `${String(profile.harness)} / ${String(profile.model)}` : '未提供'}</dd><dt>不可变方案</dt><dd>{session.planId}</dd></dl>
    {!identity && <p role="alert">原项目与方案绑定不匹配，执行已禁用。</p>}
    <UsageCommitmentSummary value={session.plan.usageBudget}/>
    {!budget && <p role="alert">缺少可核对的提供商预算，执行已禁用。</p>}
    {session.state === 'prepared' && !session.taskId && <><PlanReviewGate ownerId={ownerId} plan={session.plan} busy={busy || disabled ? 'managed-probe' : ''} act={async (_name, work) => read(work)} onAllowed={setAllowed}/><button className="primary" disabled={disabled || !identity || !budget || !allowed || session.plan.status !== 'ready'} onClick={() => void mutate(async requestId => {
      const who = await api.session(); const current = checkedAuthorization(await api.planAuthorization(session.planId));
      if (who.id !== ownerId || !current.executionAllowed) throw new ApiError('当前方案执行未获授权', 403, 'PLAN_AUTHORIZATION_REQUIRED');
      onSession(await openresearchApi.startManaged(project.id, session, requestId));
    })}>确认预算并执行单轮文本探测</button></>}
    {!session.taskId && session.state !== 'prepared' && <p className="policy-note">原执行准入待核对。不会重发探测；请核对原会话。</p>}
  </section>;
}
