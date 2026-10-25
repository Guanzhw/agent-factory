import { useEffect, useRef, useState } from 'react';
import { ApiError } from '../../../web/api.js';
import { researchApi } from './api.js';
import { defaultIterationCaps, iterationPresets, iterationSnapshot, readIterationPending, type IterationCaps, type IterationPending, type IterationPreset, type IterationSnapshot } from './iterationState.js';
const labels: Record<string, string> = { reserved: '已预留', unknown: '结果待确认', running: '执行中', ready: '改善已确认，等待下一轮', stopped: '已停止', canceling: '取消确认中', improved: '改善', tie: '持平，停止', regressed: '退步，停止', cancelled: '已取消', evaluation_unavailable: '评估不可用', round_limit: '达到轮次上限', deadline: '到达截止时间', budget_exhausted: '总预算不足' };
export function ResearchIterations({ ownerId, onTask }: { ownerId: string; onTask: (id: string) => void }) {
  const key = `factory-research-iteration:${encodeURIComponent(ownerId)}`;
  const [pending, setPending] = useState<IterationPending | null>(() => { try { return readIterationPending(localStorage.getItem(key), ownerId); } catch { return null; } });
  const [open, setOpen] = useState(!!pending), [presets, setPresets] = useState<IterationPreset[]>([]), [items, setItems] = useState<IterationSnapshot[]>([]);
  const [selected, setSelected] = useState(''), [presetId, setPresetId] = useState(''), [goal, setGoal] = useState(''), [seconds, setSeconds] = useState(600);
  const [caps, setCaps] = useState<IterationCaps>({ rounds: 2, toolCalls: 0, tokenLimit: null, amountMicros: null, currency: null });
  const [error, setError] = useState(''), [readError, setReadError] = useState(''), [busy, setBusy] = useState(false), [refresh, setRefresh] = useState(0);
  const alive = useRef(true), lock = useRef(false), generation = useRef(0);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const api = researchApi.iterations;
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController(), serial = ++generation.current;
    const valid = () => alive.current && !controller.signal.aborted && generation.current === serial;
    setReadError('');
    void api.presets(ownerId, controller.signal).then(value => { if (valid()) setPresets(iterationPresets(value)); }).catch(() => { if (valid()) setReadError('预设暂不可读，请重新读取。'); });
    void api.list(ownerId, controller.signal).then(value => {
      const rows = (value as { items: unknown[] }).items.map(item => iterationSnapshot(item, ownerId));
      if (valid()) setItems(rows);
    }).catch(() => { if (valid()) setReadError('活动暂不可读，请重新读取。'); });
    return () => controller.abort();
  }, [api, ownerId, open, refresh]);
  function retain(value: IterationPending | null) { if (value) localStorage.setItem(key, JSON.stringify(value)); else localStorage.removeItem(key); setPending(value); }
  function accept(value: unknown) {
    const snapshot = iterationSnapshot(value, ownerId);
    setItems(old => [snapshot, ...old.filter(item => item.activity.id !== snapshot.activity.id)]); setSelected(snapshot.activity.id); return snapshot;
  }
  async function action(kind: 'start' | 'advance' | 'recover' | 'reconcile' | 'cancel' | 'read') {
    if (lock.current || pending && !['recover', 'read'].includes(kind)) return;
    lock.current = true; setBusy(true); setError(''); ++generation.current;
    try {
      let result: unknown;
      if (kind === 'start') {
        const original: IterationPending = { owner: ownerId, kind: 'start', body: { presetId, goal, requestId: crypto.randomUUID(), caps: { ...caps }, deadline: Date.now() / 1000 + seconds } };
        retain(original); result = await api.start(ownerId, original.body);
        if (!alive.current) return;
        const snapshot = iterationSnapshot(result, ownerId); if (snapshot.activity.requestId !== original.body.requestId) throw new Error('Request mismatch');
        accept(snapshot); retain(null);
      } else if (kind === 'recover' && pending) {
        result = pending.kind === 'start' ? await api.recover(ownerId, pending.body.requestId) : await api.get(ownerId, pending.activityId);
        if (!alive.current) return;
        const snapshot = iterationSnapshot(result, ownerId);
        if (pending.kind === 'start' ? snapshot.activity.requestId !== pending.body.requestId : snapshot.activity.id !== pending.activityId || snapshot.activity.advanceRequests?.[pending.body.requestId] !== pending.body.previousRoundId) throw new Error('Receipt not confirmed');
        accept(snapshot); retain(null);
      } else if (current) {
        if (kind === 'advance') {
          const original: IterationPending = { owner: ownerId, kind: 'advance', activityId: current.activity.id, body: { previousRoundId: current.activity.currentRoundId, requestId: crypto.randomUUID() } };
          retain(original); result = await api.advance(ownerId, original.activityId, original.body);
          const confirmed = iterationSnapshot(result, ownerId);
          if (confirmed.activity.advanceRequests?.[original.body.requestId] !== original.body.previousRoundId) throw new Error('Advance receipt mismatch');
        }
        // Reads are pure; observation and cancellation are explicit separate commands.
        if (kind === 'read') result = await api.get(ownerId, current.activity.id);
        if (kind === 'reconcile') result = await api.reconcile(ownerId, current.activity.id);
        if (kind === 'cancel') result = await api.cancel(ownerId, current.activity.id);
        if (!alive.current) return;
        const snapshot = iterationSnapshot(result, ownerId); if (snapshot.activity.id !== current.activity.id) throw new Error('Activity mismatch');
        accept(snapshot); if (kind === 'advance') retain(null);
      }
    } catch (failure) {
      if (!alive.current) return;
      const rejected = failure instanceof ApiError && [400, 401, 403, 422, 429].includes(failure.status);
      if (rejected && kind !== 'recover') retain(null);
      setError(rejected ? '请求被拒绝：请检查当前账号权限、预设、总预算与截止时间。' : '尚未确认原请求。核对只读取原回执；不会重新提交或延长截止时间。');
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  const current = items.find(item => item.activity.id === selected), preset = presets.find(item => item.id === presetId);
  const blocked = busy || !!pending;
  return <details open={open} onToggle={event => setOpen(event.currentTarget.open)}><summary>两轮研究迭代</summary>{open && <section aria-label="两轮研究迭代">
    <p>创建即授权在本次总预算与固定截止时间内最多执行所选轮次。后台确认均方误差 MSE 严格降低（minimize）后自动开始下一轮；持平或退步停止。读取不会推进或批准原生任务，待批准操作仍需进入原生任务处理。</p>
    {readError && <p role="alert">{readError}</p>}{error && <p role="alert">{error}</p>}
    <button disabled={busy} onClick={() => setRefresh(value => value + 1)}>重新读取迭代</button>
    {pending && <aside><p>原请求待确认，内容与绝对截止时间已保存。</p><pre>{JSON.stringify(pending, null, 2)}</pre><button disabled={busy} onClick={() => void action('recover')}>核对原迭代请求</button></aside>}
    <form onSubmit={event => { event.preventDefault(); void action('start'); }}><fieldset disabled={blocked}>
      <label>迭代预设<select aria-label="迭代预设" value={presetId} onChange={event => { const value = presets.find(p => p.id === event.target.value); setPresetId(event.target.value); if (value) { setCaps(defaultIterationCaps(value)); setSeconds(value.defaultTotalSeconds); } }}><option value="">选择预设</option>{presets.map(p => <option value={p.id} key={p.id}>{p.name}</option>)}</select></label>
      {preset && <p>初始基线：{preset.baseline.kind} · MSE {preset.baseline.value}。{preset.blockers.join('；')}</p>}
      <label>研究目标<input aria-label="迭代目标" value={goal} minLength={2} maxLength={2000} required onChange={event => setGoal(event.target.value)}/></label>
      <label>总时限（秒）<input aria-label="迭代总秒数" type="number" min={1} max={3600} required value={seconds} onChange={event => setSeconds(Number(event.target.value))}/></label>
      {(['rounds', 'toolCalls', 'tokenLimit', 'amountMicros'] as const).map(field => <label key={field}>{({ rounds: '总轮次', toolCalls: '总工具调用', tokenLimit: '总 token', amountMicros: '总金额（微单位）' })[field]}{caps[field] === null ? <span>不可计量</span> : <input aria-label={`迭代预算 ${field}`} type="number" min={field === 'rounds' || field === 'toolCalls' ? 1 : 0} max={field === 'rounds' ? 2 : undefined} required value={caps[field]} onChange={event => setCaps(old => ({ ...old, [field]: Number(event.target.value) }))}/>}</label>)}
      <span>币种：{caps.currency ?? '不可计量'}</span><button disabled={!preset?.ready || goal.trim().length < 2}>创建两轮活动</button>
    </fieldset></form>
    <label>近期活动<select aria-label="选择迭代活动" value={selected} disabled={busy} onChange={event => setSelected(event.target.value)}><option value="">选择活动</option>{items.map(item => <option key={item.activity.id} value={item.activity.id}>{item.activity.goal} · {labels[item.activity.status] ?? item.activity.status}</option>)}</select></label>
    {current && <article><h3>{current.activity.goal}</h3><p>{labels[current.activity.status] ?? current.activity.status} · {labels[current.activity.stopReason ?? ''] ?? current.activity.stopReason}</p>
      <p>固定截止时间：{new Date(current.activity.deadline * 1000).toLocaleString()}。取消或结果待确认时，占用预算在结算确认前仍保留。</p><p>当前选定基线：{current.activity.baselineSource.kind} · MSE {current.activity.baselineSource.metricValue} · {current.activity.baselineSource.sha256}</p>
      <p>总轮次 {current.activity.caps.rounds}；已分配 {current.budget.allocatedRounds}；占用 {current.budget.allocations.filter(a => a.state !== 'SETTLED').length}；已结算 {current.budget.allocations.filter(a => a.state === 'SETTLED').length}。</p>
      <p>总工具调用 {current.activity.caps.toolCalls}；占用 {current.budget.heldToolCalls}；已结算 {current.budget.settledToolCalls}。</p>
      <p>Token：{current.budget.usage ? `总额 ${current.activity.caps.tokenLimit}，占用 ${current.budget.usage.held_tokens}，已结算 ${current.budget.usage.settled_tokens}` : '不可计量（不代表消耗为 0）'}；金额：{current.budget.usage ? `总额 ${current.activity.caps.amountMicros}，占用 ${current.budget.usage.held_amount}，已结算 ${current.budget.usage.settled_amount} ${current.activity.caps.currency}（微单位）` : '不可计量（不代表消耗为 0）'}</p>
      <ol>{current.rounds.map(round => <li key={round.id}>第 {round.ordinal} 轮 · {round.state} · 前轮 {round.previousRoundId ?? '无'}<p>基线 MSE {round.baselineSource.metricValue} · {round.baselineSource.sha256}；候选 MSE {round.observation?.evaluation?.candidateValue ?? '待确认'} · {labels[round.decision ?? ''] ?? round.decision}</p><button onClick={() => onTask(round.taskId)}>{round.observation?.approvalRequired ? '前往原生任务处理待批准操作' : '查看原生任务'}</button></li>)}</ol>
      <button disabled={busy} onClick={() => void action('read')}>读取当前活动</button><button disabled={blocked || current.activity.status === 'stopped'} onClick={() => void action('reconcile')}>核对执行与结算</button><button disabled={blocked || current.activity.status !== 'ready'} onClick={() => void action('advance')}>继续下一轮</button><button disabled={blocked || current.activity.cancelRequested || current.activity.status === 'stopped'} onClick={() => void action('cancel')}>取消活动</button>
    </article>}
  </section>}</details>;
}
