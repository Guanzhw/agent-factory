import { useEffect, useRef, useState } from 'react';
import { useCommandKeys } from './commandKeys.js';
import { checkedAuthorization, checkedReview, recoverPlanReviews, requestReviewOnce } from './planReviewState.js';
import { api } from './api.js';
import { UsageCommitmentSummary } from './UsageLedger.js';
import { ProjectCreationReview, projectCreationSummary, needsProjectCreationSummary } from './ProjectCreationReview.js';
import { usageCommitment } from './usageLedgerState.js';
import type { Plan, PlanAuthorization, PlanReview } from './models.js';

type Act = (name: string, work: () => Promise<void>) => Promise<void>;
const policyNames: Record<string, string> = { 'admin-review': '管理员审查', 'read-only-auto': '只读范围自动执行', 'bounded-synthetic': '有界合成演示', unset: '执行已停用' };
const message = (e: unknown) => e instanceof Error ? e.message : '审查状态无法确认，请刷新。';

export function PlanReviewGate({ ownerId, plan, busy, act, onAllowed }: { ownerId: string; plan: Plan; busy: string; act: Act; onAllowed: (allowed: boolean) => void }) {
  const scope = `${ownerId}:${plan.id}:${plan.fingerprint}`;
  const identity = useRef({ scope, epoch: 0 });
  if (identity.current.scope !== scope) identity.current = { scope, epoch: identity.current.epoch + 1 };
  const epoch = identity.current.epoch;
  const currentScope = useRef(scope); currentScope.current = scope;
  const [snapshot, setSnapshot] = useState<{ scope: string; state: PlanAuthorization; recovery: ReturnType<typeof recoverPlanReviews> }>();
  const [error, setError] = useState('');
  const [readyScope, setReadyScope] = useState('');
  const [refresh, setRefresh] = useState(0);
  const keys = useCommandKeys(ownerId);
  const pendingRequest = useRef<{ scope: string; id: string } | undefined>(undefined);
  const ready = readyScope === scope && snapshot?.scope === scope;
  const state = ready ? snapshot.state : undefined;
  const recovery = ready ? snapshot.recovery : undefined;
  const review = recovery?.review;
  useEffect(() => {
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    setReadyScope(''); setSnapshot(undefined); setError(''); onAllowed(false);
    if (pendingRequest.current?.scope !== scope) pendingRequest.current = undefined;
    async function poll() {
      try {
        const [session, raw, reviews] = await Promise.all([api.session(controller.signal), api.planAuthorization(plan.id, controller.signal), api.planReviews(false, controller.signal, plan.id)]);
        if (session.id !== ownerId) throw new Error('当前身份无法核对。');
        const state = checkedAuthorization(raw); const recovery = recoverPlanReviews(reviews, ownerId, plan, state);
        if (state.ownerSubmissionSupported === true && (state.ownerId !== ownerId || state.planId !== plan.id || state.planFingerprint !== plan.fingerprint)) throw new Error('当前身份或方案范围无法核对。');
        if (controller.signal.aborted || (currentScope.current !== scope || identity.current.epoch !== epoch)) return;
        if (pendingRequest.current?.scope === scope && reviews.some(item => checkedReview(item).requestId === pendingRequest.current?.id)) pendingRequest.current = undefined;
        setSnapshot({ scope, state, recovery }); setReadyScope(scope); setError(''); onAllowed(state.executionAllowed || state.ownerSubmissionSupported === true);
      } catch (e) { if (!controller.signal.aborted && (currentScope.current === scope && identity.current.epoch === epoch)) { setError(message(e)); setReadyScope(''); onAllowed(false); } }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 2500);
    }
    void poll(); return () => { controller.abort(); clearTimeout(timer); onAllowed(false); };
  }, [ownerId, plan.id, plan.fingerprint, scope, epoch, refresh, onAllowed]);
  async function requestReview() {
    if (!ready || !state || !recovery?.canRequest || plan.status !== 'ready') return;
    await act('request-plan-review', async () => {
      const key = await keys('request-plan-review', { planId: plan.id, fingerprint: plan.fingerprint, policy: state.policy.fingerprint, previousReview: review?.id ?? null });
      if ((currentScope.current !== scope || identity.current.epoch !== epoch)) return;
      const requestId = pendingRequest.current?.scope === scope ? pendingRequest.current.id : key.requestId;
      pendingRequest.current = { scope, id: requestId };
      setReadyScope(''); onAllowed(false);
      // Re-read before dispatch: another tab may already have submitted a review.
      const session = await api.session();
      const authorization = checkedAuthorization(await api.planAuthorization(plan.id));
      const existing = recoverPlanReviews(await api.planReviews(false, undefined, plan.id), ownerId, plan, authorization);
      if (session.id !== ownerId || (currentScope.current !== scope || identity.current.epoch !== epoch)) return;
      if (authorization.policy.fingerprint !== state.policy.fingerprint || !existing.canRequest) { pendingRequest.current = undefined; setRefresh(n => n + 1); return; }
      const check = (value: unknown) => {
        const result = checkedReview(value);
        recoverPlanReviews([result], ownerId, plan, authorization);
        if (result.planId !== plan.id || result.policyDigest !== authorization.policy.fingerprint || result.policyRevision !== authorization.policy.revision) throw new Error('审查回执与原方案或策略不一致。');
        return result;
      };
      try {
        await requestReviewOnce(() => api.requestPlanReview(plan.id, requestId), () => api.planReviews(false, undefined, plan.id), check, requestId);
        if ((currentScope.current !== scope || identity.current.epoch !== epoch)) return;
        key.acknowledged(); pendingRequest.current = undefined; setRefresh(n => n + 1);
      } catch (e) { if ((currentScope.current === scope && identity.current.epoch === epoch)) { setError('请求尚未确认；请先刷新核对，显式重试沿用原请求标识。'); setRefresh(n => n + 1); } throw e; }
    });
  }
  if (ready && state?.ownerSubmissionSupported === true && !state.reviewRequired) return <p className="quiet" role="status">提交即确认此次业务范围；服务端仍核对当前身份和资源权限。</p>;
  return <section className="plan-review-gate" aria-label="方案执行授权"><h3>方案执行授权</h3><p>{state ? policyNames[state.policy.name] ?? '策略待确认' : '正在核对授权与已有审查'} · {state?.executionAllowed ? '当前允许执行' : state?.reviewRequired ? '需要管理员审查' : '当前不允许执行'}</p>{error && <div role="alert" className="error-message">{error}</div>}
    {review && <p role="status">审查状态：{review.decision === 'pending' ? '等待决定' : review.decision === 'approved' ? '已同意' : '已拒绝'}{review.expired ? ' · 已过期' : ''}{!review.currentPolicy ? ' · 策略已变更' : ''}。有效期至 {new Date(review.expiresAt).toLocaleString('zh-CN')}。<small>审查 {review.id}</small></p>}
    {recovery?.pending && <p className="quiet">已有当前方案的待审查请求，正在等待管理员决定；不会重复申请。</p>}
    {recovery?.truncated && <p className="policy-note">仅取得最近 100 条审查记录，无法确认更早记录；暂不创建新的审查请求。</p>}
    {state?.reviewRequired && !state.executionAllowed && <><p className="quiet">审查只授权这一份方案、当前策略版本及有效期。实验还需单独确认。</p><button className="secondary wide" disabled={!!busy || !ready || !recovery?.canRequest || plan.status !== 'ready'} onClick={() => void requestReview()}>{pendingRequest.current?.scope === scope ? '核对并重试原审查请求' : review ? '明确提交新的审查请求' : '提交方案审查'}</button></>}
    <button className="text-button" disabled={!!busy} onClick={() => setRefresh(n => n + 1)}>刷新授权与审查状态</button></section>;
}

export function PlanReviews({ ownerId, busy, act }: { ownerId: string; busy: string; act: Act }) {
  const [reviews, setReviews] = useState<PlanReview[]>([]);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const keys = useRef(new Map<string, string>());
  const identity = useRef({ ownerId, epoch: 0 });
  if (identity.current.ownerId !== ownerId) identity.current = { ownerId, epoch: identity.current.epoch + 1 };
  const epoch = identity.current.epoch;
  const currentOwner = useRef(ownerId); currentOwner.current = ownerId;
  const [readyOwner, setReadyOwner] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    setReviews([]); setError(''); setReadyOwner('');
    async function poll() {
      try { const [session, values] = await Promise.all([api.session(controller.signal), api.planReviews(true, controller.signal)]); if (session.id !== ownerId || session.role !== 'manager' || !Array.isArray(values)) throw new Error('当前管理身份或审查列表无法核对。'); const next = values.map(checkedReview); if (!controller.signal.aborted && (currentOwner.current === ownerId && identity.current.epoch === epoch)) { setReviews(next); setReadyOwner(ownerId); setError(''); } }
      catch (e) { if (!controller.signal.aborted && (currentOwner.current === ownerId && identity.current.epoch === epoch)) { setError(message(e)); setReadyOwner(''); } }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 4000);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [ownerId, epoch, refresh]);
  async function decide(review: PlanReview, approved: boolean) {
    if (readyOwner !== ownerId || (currentOwner.current !== ownerId || identity.current.epoch !== epoch)) return;
    const key = `${ownerId}:${review.id}:${approved}`;
    if (!keys.current.has(key)) keys.current.set(key, crypto.randomUUID());
    await act('decide-plan-review', async () => { const session = await api.session(); const current = checkedReview(await api.inspectPlanReview(review.id)); if ((currentOwner.current !== ownerId || identity.current.epoch !== epoch) || session.id !== ownerId || session.role !== 'manager') return; if (current.id !== review.id || current.ownerId !== review.ownerId || current.planDigest !== review.planDigest || current.planFingerprint !== review.planFingerprint || current.policyDigest !== checkedReview(review).policyDigest || current.policyRevision !== review.policyRevision || current.decision !== 'pending' || current.expired || !current.currentPolicy || !current.planIntegrityMatches) throw new Error('审查范围或当前状态已变更，请刷新。'); if (approved && needsProjectCreationSummary(current) && !projectCreationSummary(current)) throw new Error('固定项目创建范围无法核对，请刷新后审阅。'); setReadyOwner(''); try { const saved = checkedReview(await api.decidePlanReview(review.id, approved, keys.current.get(key)!)); if (saved.id !== current.id || saved.ownerId !== current.ownerId || saved.planId !== current.planId || saved.planDigest !== current.planDigest || saved.planFingerprint !== current.planFingerprint || saved.policyDigest !== current.policyDigest || saved.policyRevision !== current.policyRevision || saved.reviewerId !== ownerId || saved.decision !== (approved ? 'approved' : 'denied')) throw new Error('决定回执无法核对。'); } finally { if ((currentOwner.current === ownerId && identity.current.epoch === epoch)) setRefresh(n => n + 1); } });
  }
  return <section className="plan-reviews-page"><div className="page-heading"><div><h1>方案审查</h1><p>检查一次任务的固定范围。此决定不会发布材料，也不会替代实验确认。</p></div><button className="secondary" disabled={!!busy} onClick={() => setRefresh(n => n + 1)}>刷新审查</button></div>{error && <div role="alert" className="error-message">{error}</div>}{readyOwner === ownerId && reviews.length ? reviews.map(review => <article className="material-row review-row" key={review.id}><div className="material-info"><h2>{review.planSummary?.normalizedGoal ?? '待核对方案'}</h2><p>申请人 {review.ownerId} · {({ pending: '待审查', approved: '已同意', denied: '已拒绝' })[review.decision]}{review.expired ? ' · 已过期' : ''}{!review.currentPolicy ? ' · 策略已变更' : ''}</p><ReviewProjectScope review={review}/><dl className="plan-details"><dt>工具范围</dt><dd>{review.planSummary?.tools?.join('、') ?? '未提供，不能据此确认范围'}</dd><dt>能力范围</dt><dd>{review.planSummary?.capabilities?.join('、') ?? '未提供'}</dd><dt>有效期</dt><dd>{new Date(review.expiresAt).toLocaleString('zh-CN')}</dd></dl><UsageCommitmentSummary value={review.planSummary?.usageBudget}/><details className="technical-detail"><summary>固定应用配置、预算与方案凭据</summary><h3>固定应用配置</h3><pre>{JSON.stringify(review.planSummary?.config ?? {}, null, 2)}</pre><h3>固定预算</h3><pre>{JSON.stringify(review.planSummary?.budget ?? {}, null, 2)}</pre><span>方案 {review.planId}</span><span>方案摘要 {review.planDigest}</span><span>策略版本 {review.policyRevision}</span><span>审批人 {review.reviewerId ?? '尚未决定'}</span><pre>{JSON.stringify(review.planSummary?.materialRefs ?? [], null, 2)}</pre></details></div><div className="material-actions">{review.decision === 'pending' && <><button className="primary" disabled={!!busy || readyOwner !== ownerId || review.expired || !review.currentPolicy || !review.planSummary || needsProjectCreationSummary(review) && !projectCreationSummary(review) || review.planIntegrityMatches !== true || review.planSummary?.usageBudget !== undefined && !usageCommitment(review.planSummary.usageBudget)} onClick={() => void decide(review, true)}>同意方案</button><button className="secondary danger" disabled={!!busy || readyOwner !== ownerId || review.expired || !review.currentPolicy} onClick={() => void decide(review, false)}>拒绝方案</button></>}</div></article>) : <p className="list-empty">暂无可见审查请求。</p>}</section>;
}

function ReviewProjectScope({ review }: { review: PlanReview }) {
  const value = projectCreationSummary(review);
  return value ? <ProjectCreationReview value={value}/> : needsProjectCreationSummary(review) ? <p role="alert" className="error-message">固定项目创建输入与费用范围无法核对，暂不能同意方案。请刷新审查。</p> : null;
}
