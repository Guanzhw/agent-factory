import { useEffect, useRef, useState } from 'react';
import { api } from './api.js';
import type { Plan, PlanAuthorization, PlanReview } from './models.js';

type Act = (name: string, work: () => Promise<void>) => Promise<void>;
const policyNames: Record<string, string> = { 'admin-review': '管理员审查', 'read-only-auto': '只读范围自动执行', 'bounded-synthetic': '有界合成演示', unset: '执行已停用' };
const message = (e: unknown) => e instanceof Error ? e.message : '审查状态无法确认，请刷新。';

export function PlanReviewGate({ plan, busy, act, onAllowed }: { plan: Plan; busy: string; act: Act; onAllowed: (allowed: boolean) => void }) {
  const [state, setState] = useState<PlanAuthorization>(plan.authorization ?? { executionAllowed: false, reviewRequired: false, policy: { name: 'unset', revision: '', fingerprint: '', review_ttl_seconds: 0 }, nativeToolConfirmationSeparate: true });
  const [error, setError] = useState('');
  const [review, setReview] = useState<PlanReview>();
  const [refresh, setRefresh] = useState(0);
  const requestId = useRef('');
  const reviewRef = useRef<PlanReview | undefined>(undefined);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    onAllowed(false);
    async function poll() {
      try {
        const next = await api.planAuthorization(plan.id, controller.signal);
        const currentReview = reviewRef.current ? await api.inspectPlanReview(reviewRef.current.id, controller.signal) : undefined;
        if (!controller.signal.aborted) { setState(next); setError(''); onAllowed(next.executionAllowed === true); if (currentReview) { setReview(currentReview); reviewRef.current = currentReview; } }
      } catch (e) { if (!controller.signal.aborted) { setError(message(e)); onAllowed(false); } }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 2500);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [plan.id, refresh, onAllowed]);
  async function requestReview() {
    if (reviewRef.current?.expired || reviewRef.current?.decision === 'denied' || reviewRef.current?.currentPolicy === false) requestId.current = '';
    requestId.current ||= crypto.randomUUID();
    await act('request-plan-review', async () => { const saved = await api.requestPlanReview(plan.id, requestId.current); reviewRef.current = saved; setReview(saved); setRefresh(n => n + 1); });
  }
  return <section className="plan-review-gate" aria-label="方案执行授权"><h3>方案执行授权</h3><p>{policyNames[state.policy?.name] ?? '策略待确认'} · {state.executionAllowed ? '当前允许执行' : state.reviewRequired ? '需要管理员审查' : '当前不允许执行'}</p>{error && <div role="alert" className="error-message">{error}</div>}{state.reviewRequired && !state.executionAllowed && <><p className="quiet">审查只授权这一份方案、当前策略版本及有效期。实验还需单独确认。</p><button className="secondary wide" disabled={!!busy || plan.status !== 'ready'} onClick={() => void requestReview()}>{review?.expired || review?.decision === 'denied' || review?.currentPolicy === false ? '提交新的审查请求' : review ? '核对原审查请求' : '提交方案审查'}</button>{review && <p role="status" className="quiet">审查状态：{review.decision === 'pending' ? '等待决定' : review.decision === 'approved' ? '已同意' : '已拒绝'}。有效期至 {new Date(review.expiresAt).toLocaleString('zh-CN')}。</p>}</>}<button className="text-button" disabled={!!busy} onClick={() => setRefresh(n => n + 1)}>刷新授权状态</button></section>;
}

export function PlanReviews({ busy, act }: { busy: string; act: Act }) {
  const [reviews, setReviews] = useState<PlanReview[]>([]);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const keys = useRef(new Map<string, string>());
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const next = await api.planReviews(true, controller.signal); if (!controller.signal.aborted) { setReviews(next); setError(''); } }
      catch (e) { if (!controller.signal.aborted) setError(message(e)); }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 4000);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [refresh]);
  async function decide(review: PlanReview, approved: boolean) {
    const key = `${review.id}:${approved}`;
    if (!keys.current.has(key)) keys.current.set(key, crypto.randomUUID());
    await act('decide-plan-review', async () => { await api.decidePlanReview(review.id, approved, keys.current.get(key)!); setRefresh(n => n + 1); });
  }
  return <section className="plan-reviews-page"><div className="page-heading"><div><h1>方案审查</h1><p>检查一次任务的固定范围。此决定不会发布材料，也不会替代实验确认。</p></div><button className="secondary" disabled={!!busy} onClick={() => setRefresh(n => n + 1)}>刷新审查</button></div>{error && <div role="alert" className="error-message">{error}</div>}{reviews.length ? reviews.map(review => <article className="material-row review-row" key={review.id}><div className="material-info"><h2>{review.planSummary?.normalizedGoal ?? '待核对方案'}</h2><p>申请人 {review.ownerId} · {({ pending: '待审查', approved: '已同意', denied: '已拒绝' })[review.decision]}{review.expired ? ' · 已过期' : ''}{!review.currentPolicy ? ' · 策略已变更' : ''}</p><dl className="plan-details"><dt>工具范围</dt><dd>{review.planSummary?.tools?.join('、') ?? '未提供，不能据此确认范围'}</dd><dt>能力范围</dt><dd>{review.planSummary?.capabilities?.join('、') ?? '未提供'}</dd><dt>有效期</dt><dd>{new Date(review.expiresAt).toLocaleString('zh-CN')}</dd><dt>固定预算</dt><dd><pre>{JSON.stringify(review.planSummary?.budget ?? {}, null, 2)}</pre></dd></dl><details className="technical-detail"><summary>方案与策略凭据</summary><span>方案 {review.planId}</span><span>方案摘要 {review.planDigest}</span><span>策略版本 {review.policyRevision}</span><span>审批人 {review.reviewerId ?? '尚未决定'}</span><pre>{JSON.stringify(review.planSummary?.materialRefs ?? [], null, 2)}</pre></details></div><div className="material-actions">{review.decision === 'pending' && <><button className="primary" disabled={!!busy || review.expired || !review.currentPolicy || !review.planSummary || review.planIntegrityMatches === false} onClick={() => void decide(review, true)}>同意方案</button><button className="secondary danger" disabled={!!busy || review.expired || !review.currentPolicy} onClick={() => void decide(review, false)}>拒绝方案</button></>}</div></article>) : <p className="list-empty">暂无可见审查请求。</p>}</section>;
}
