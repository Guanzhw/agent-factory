import { useEffect, useRef, useState } from 'react';
import { sessionTriggersApi as api, triggerSourceLabels, type TriggerPage, type TriggerSource } from './sessionTriggersClient.js';

type Draft = { title: string; instruction: string; source: TriggerSource; eventType: string; cron: string; timezone: string; keyword: string };
const initialDraft: Draft = { title: '', instruction: '', source: 'research', eventType: '', cron: '0 9 * * *', timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, keyword: '' };
const errorText = (error: unknown) => error instanceof Error ? error.message : '触发器操作失败，请重试。';
const date = (value: number) => new Date(value * 1000).toLocaleString('zh-CN');
const deliveryStates: Record<string, string> = { pending: '等待执行', dispatched: '已发起', failed: '触发失败', stopped: '已停止触发' };

export function SessionTriggers({ ownerId, sessionId, stopped, open }: { ownerId: string; sessionId: string; stopped: boolean; open: boolean }) {
  const [draft, setDraft] = useState(initialDraft);
  const [page, setPage] = useState<TriggerPage | null>(null);
  const [readError, setReadError] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const requestId = useRef(crypto.randomUUID());
  const removals = useRef(new Map<string, string>());
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    async function read() {
      try {
        const result = await api.list(ownerId, sessionId, controller.signal);
        if (!controller.signal.aborted) { setPage(result); setReadError(''); }
      } catch (reason) { if (!controller.signal.aborted) setReadError(errorText(reason)); }
    }
    void read();
    return () => controller.abort();
  }, [ownerId, sessionId, open, refresh]);
  function change(value: Partial<Draft>) { setDraft(current => ({ ...current, ...value })); requestId.current = crypto.randomUUID(); }
  async function add() {
    setBusy(true); setError(''); setNotice('');
    try {
      await api.create(ownerId, sessionId, {
        requestId: requestId.current, title: draft.title.trim() || draft.instruction.trim().slice(0, 60), instruction: draft.instruction.trim(), source: draft.source,
        ...(draft.source === 'external' ? { eventType: draft.eventType.trim() } : {}),
        ...(draft.source === 'cron' ? { cron: draft.cron.trim(), timezone: draft.timezone.trim() } : {}),
        ...(draft.source === 'research' && draft.keyword.trim() ? { keyword: draft.keyword.trim() } : {}),
      });
      change({ title: '', instruction: '' }); setNotice('触发器已添加。'); setRefresh(value => value + 1);
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }
  async function remove(id: string) {
    setBusy(true); setError(''); setNotice('');
    const original = removals.current.get(id) ?? crypto.randomUUID(); removals.current.set(id, original);
    try { await api.remove(ownerId, sessionId, id, original); setNotice('触发器已删除。'); setRefresh(value => value + 1); }
    catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }
  return <section className="rs-triggers" aria-label="自动触发设置">
    <p>来源有新事件时，助手会在本对话中执行你留下的指令。</p>
    {stopped && <p role="status">会话已停止，后续事件不会发起新一轮。添加触发器将恢复自动触发。</p>}
    {readError && <p className="rw-error" role="alert">{readError}</p>}
    <button type="button" onClick={() => setRefresh(value => value + 1)}>刷新触发器</button>
    {!page && !readError && <p role="status">正在读取触发器…</p>}
    {page && <ul className="rs-trigger-list">{page.items.filter(item => item.enabled).map(item => {
      const deliveries = page.deliveries.filter(value => value.triggerId === item.id).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
      const delivery = deliveries[0];
      return <li key={item.id}><strong>{item.title}</strong><span>{triggerSourceLabels[item.source]}{item.source === 'external' && ` · ${item.eventType}`}</span>
        {item.source === 'cron' && <span>{item.cron} · {item.timezone}{item.nextRunAt && ` · 下次 ${date(item.nextRunAt)}`}</span>}
        {item.source === 'research' && item.keyword && <span>关键词：{item.keyword}</span>}
        <p>{item.instruction}</p>
        {delivery && <span role="status">最近事件：{deliveryStates[delivery.state] ?? delivery.state}{delivery.error && ` · ${delivery.error}`}</span>}
        {deliveries.length > 0 && <details><summary>触发记录 · {deliveries.length}</summary>{deliveries.map(value => <p key={value.id}><time dateTime={value.createdAt}>{new Date(value.createdAt).toLocaleString('zh-CN')}</time> · {deliveryStates[value.state] ?? value.state}{value.error && ` · ${value.error}`}<br/><small>事件：{value.eventId}{value.turnId && ` · 轮次：${value.turnId}`}</small></p>)}</details>}
        <button type="button" aria-label={`删除触发器 ${item.title}`} disabled={busy} onClick={() => void remove(item.id)}>删除</button>
      </li>;
    })}</ul>}
    {page && !page.items.some(item => item.enabled) && <p className="rw-muted">还没有自动触发器。</p>}
    <form className="rw-form" onSubmit={event => { event.preventDefault(); void add(); }}><fieldset disabled={busy}>
      <h4>添加触发器</h4>
      <label>触发来源<select value={draft.source} onChange={event => change({ source: event.target.value as TriggerSource })}>{Object.entries(triggerSourceLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      {draft.source === 'external' && <><label>事件名称<input required value={draft.eventType} placeholder="例如 deploy.completed" onChange={event => change({ eventType: event.target.value })}/></label><p>通过 <code>POST /api/factory/research/events</code> 发送 <code>{'{requestId, eventType, payload}'}</code>，使用已登录成员的会话。</p></>}
      {draft.source === 'cron' && <><label>Cron 表达式<input required value={draft.cron} onChange={event => change({ cron: event.target.value })}/></label><small>分 时 日 月 周，例如 0 9 * * * 表示每天 09:00。</small><label>时区<input required value={draft.timezone} placeholder="Asia/Shanghai" onChange={event => change({ timezone: event.target.value })}/></label></>}
      {draft.source === 'research' && <><p>可见的团队研究资料发布后，将作为新事件交给助手。</p><label>关键词（可选）<input value={draft.keyword} placeholder="例如 agent memory；留空接收全部" onChange={event => change({ keyword: event.target.value })}/></label></>}
      <label>名称（可选）<input value={draft.title} onChange={event => change({ title: event.target.value })}/></label>
      <label>触发后执行的指令<textarea required rows={3} value={draft.instruction} placeholder="例如：分析新资料与当前研究的关系，并更新结论。" onChange={event => change({ instruction: event.target.value })}/></label>
      <button className="rw-primary" type="submit">{busy ? '正在保存…' : '添加触发器'}</button>
    </fieldset></form>
    {notice && <p role="status">{notice}</p>}{error && <p className="rw-error" role="alert">{error}</p>}
  </section>;
}
