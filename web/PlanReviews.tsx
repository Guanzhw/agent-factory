import { useEffect, useRef, useState } from 'react';
import { checkedPlanAuthorization, checkedReview } from './planReviewState.js';
import { api } from './api.js';
import { UsageCommitmentSummary } from './UsageLedger.js';
import { ProjectCreationReview, projectCreationSummary } from './ProjectCreationReview.js';
import type { Plan, PlanAuthorization, PlanReview } from './models.js';

type Act = (name: string, work: () => Promise<void>) => Promise<void>;
const message = (e: unknown) => e instanceof Error ? e.message : '当前方案状态无法确认，请刷新。';

/** Current identity and immutable scope are checked once; starting remains an explicit owner action. */
export function PlanReviewGate({ ownerId, plan, busy, onAllowed }: { ownerId: string; plan: Plan; busy: string; act: Act; onAllowed: (allowed: boolean) => void }) {
  const scope = `${ownerId}:${plan.id}:${plan.fingerprint}`;
  const identity = useRef({ scope, epoch: 0 });
  if (identity.current.scope !== scope) identity.current = { scope, epoch: identity.current.epoch + 1 };
  const epoch = identity.current.epoch;
  const [snapshot, setSnapshot] = useState<{ scope: string; state: PlanAuthorization }>();
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const state = snapshot?.scope === scope ? snapshot.state : undefined;
  useEffect(() => {
    const controller = new AbortController();
    setSnapshot(undefined); setError(''); onAllowed(false);
    async function check() {
      try {
        const [session, raw] = await Promise.all([api.session(controller.signal), api.planAuthorization(plan.id, controller.signal)]);
        if (session.id !== ownerId) throw new Error('当前身份无法核对。');
        const next = checkedPlanAuthorization(raw, ownerId, plan);
        if (controller.signal.aborted || identity.current.scope !== scope || identity.current.epoch !== epoch) return;
        setSnapshot({ scope, state: next });
        onAllowed(plan.status === 'ready' && !next.reviewRequired && next.executionAllowed);
      } catch (e) {
        if (!controller.signal.aborted && identity.current.scope === scope && identity.current.epoch === epoch) { setError(message(e)); onAllowed(false); }
      }
    }
    void check(); return () => { controller.abort(); onAllowed(false); };
  }, [ownerId, plan.id, plan.fingerprint, plan.status, scope, epoch, refresh, onAllowed]);
  const allowed = state && plan.status === 'ready' && !state.reviewRequired && state.executionAllowed;
  return <section className="plan-review-gate" aria-label="任务提交检查">
    {allowed ? <p className="quiet" role="status">提交即确认此次业务范围；服务端仍核对当前身份和资源权限。</p> : <p role="status">{state ? state.message || '当前方案不能提交。旧方案和历史决定保持原状，请重新生成方案。' : error ? '当前不允许执行。' : '正在核对当前身份与方案。'}</p>}
    {error && <div role="alert" className="error-message">{error}</div>}
    {!allowed && <button className="text-button" disabled={!!busy} onClick={() => setRefresh(n => n + 1)}>刷新提交状态</button>}
  </section>;
}

export function PlanReviews({ ownerId, busy }: { ownerId: string; busy: string; act: Act }) {
  const [reviews, setReviews] = useState<PlanReview[]>([]);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const identity = useRef({ ownerId, epoch: 0 });
  if (identity.current.ownerId !== ownerId) identity.current = { ownerId, epoch: identity.current.epoch + 1 };
  const epoch = identity.current.epoch;
  const [readyOwner, setReadyOwner] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setReviews([]); setError(''); setReadyOwner('');
    async function read() {
      try {
        const session = await api.session(controller.signal);
        if (session.id !== ownerId) throw new Error('当前身份无法核对。');
        const values = await api.planReviews(session.role === 'manager', controller.signal);
        if (!Array.isArray(values)) throw new Error('历史审查列表无法核对。');
        const next = values.map(checkedReview);
        if (session.role !== 'manager' && next.some(item => item.ownerId !== ownerId)) throw new Error('历史审查归属无法核对。');
        if (!controller.signal.aborted && identity.current.ownerId === ownerId && identity.current.epoch === epoch) { setReviews(next); setReadyOwner(ownerId); setError(''); }
      } catch (e) { if (!controller.signal.aborted && identity.current.ownerId === ownerId && identity.current.epoch === epoch) setError(message(e)); }
    }
    void read(); return () => controller.abort();
  }, [ownerId, epoch, refresh]);
  return <section className="plan-reviews-page"><div className="page-heading"><div><h1>历史方案审查</h1><p>旧审查记录只读保留。新任务由成员确认范围后提交；历史待审查、拒绝和未知状态不会自动执行。</p></div><button className="secondary" disabled={!!busy} onClick={() => setRefresh(n => n + 1)}>刷新历史记录</button></div>{error && <div role="alert" className="error-message">{error}</div>}{readyOwner === ownerId && reviews.length ? reviews.map(review => <article className="material-row review-row" key={review.id}><div className="material-info"><h2>{review.planSummary?.normalizedGoal ?? '历史方案'}</h2><p>申请人 {review.ownerId} · {({ pending: '历史待审查', approved: '历史已同意', denied: '历史已拒绝' })[review.decision]}{review.expired ? ' · 已过期' : ''}</p><ReviewProjectScope review={review}/><dl className="plan-details"><dt>工具范围</dt><dd>{review.planSummary?.tools?.join('、') ?? '未提供'}</dd><dt>能力范围</dt><dd>{review.planSummary?.capabilities?.join('、') ?? '未提供'}</dd><dt>原有效期</dt><dd>{new Date(review.expiresAt).toLocaleString('zh-CN')}</dd></dl><UsageCommitmentSummary value={review.planSummary?.usageBudget}/><details className="technical-detail"><summary>固定应用配置、预算与历史凭据</summary><pre>{JSON.stringify(review.planSummary?.config ?? {}, null, 2)}</pre><pre>{JSON.stringify(review.planSummary?.budget ?? {}, null, 2)}</pre><span>方案 {review.planId}</span><span>方案摘要 {review.planDigest}</span><span>原策略版本 {review.policyRevision}</span><span>审批人 {review.reviewerId ?? '无历史决定'}</span><pre>{JSON.stringify(review.planSummary?.materialRefs ?? [], null, 2)}</pre></details></div></article>) : <p className="list-empty">暂无可见历史审查记录。</p>}</section>;
}

function ReviewProjectScope({ review }: { review: PlanReview }) {
  const value = projectCreationSummary(review);
  return value ? <ProjectCreationReview value={value}/> : null;
}
