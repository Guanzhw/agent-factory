import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api.js';
import { eventCopy, type EventPage, type JobEvent } from './models.js';

function timestamp(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? '未知' : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function EventTimeline({ jobId, latest }: { jobId: string; latest: JobEvent[] }) {
  const [page, setPage] = useState<EventPage>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [prefixChanged, setPrefixChanged] = useState(false);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => { pending.current?.abort(); }, []);
  const events = page?.events ?? latest;
  async function load(fromStart: boolean) {
    if (pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true); setError('');
    try {
      const next = await api.events(jobId, fromStart ? undefined : page?.nextCursor, controller.signal);
      if (controller.signal.aborted) return;
      if (!fromStart && page && (next.streamId !== page.streamId || next.afterSequence !== page.endSequence)) {
        throw new ApiError('事件流或分页位置发生变化，请从头核对。', 409, 'EVENT_PREFIX_CHANGED');
      }
      setPage(next); setPrefixChanged(false);
    } catch (failure) {
      if (controller.signal.aborted) return;
      setPrefixChanged(failure instanceof ApiError && failure.code === 'EVENT_PREFIX_CHANGED');
      setError(failure instanceof Error ? failure.message : '读取事件记录失败，请重试原分页。');
    } finally {
      pending.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  function recent() { setPage(undefined); setError(''); setPrefixChanged(false); }
  return <section aria-label="执行事件记录"><div className="section-heading"><h3>执行时间线</h3><span className="quiet">{page ? `历史 ${page.startSequence ?? 0}–${page.endSequence ?? 0} / ${page.highWatermarkSequence}` : `最近 ${events.length} 条记录`}</span></div>
    <div className="button-row"><button className="secondary" disabled={busy} onClick={() => void load(true)}>{busy ? '读取记录…' : page ? '从头重新核对' : '查看完整历史'}</button>{page && <><button className="secondary" disabled={busy || !page.hasMore || prefixChanged} onClick={() => void load(false)}>下一页</button><button className="secondary" disabled={busy} onClick={recent}>返回最近记录</button></>}</div>
    {error && <div role="alert" className="error-message">{error}{prefixChanged && <p>较早事件的提交顺序发生变化，请从头核对；不会重放任务。</p>}</div>}
    {page && <p className="quiet">每页最多 100 条。显示的是服务端本次读取的历史记录；新记录可从头核对，或返回最近记录。</p>}
    {events.length ? <ol className="timeline">{events.map(event => { const copy = eventCopy(event); return <li key={event.id}><time>{timestamp(event.createdAt)}</time><div><strong>{copy.title}</strong><p>{copy.message}</p><details className="technical-detail"><summary>事件记录详情</summary><span>类型：{event.type}</span><span>原始记录：{event.message}</span><span>记录标识：{event.id}</span>{'sequence' in event && <span>流内顺序：{String(event.sequence)}</span>}{event.data && <pre>{JSON.stringify(event.data, null, 2)}</pre>}</details></div></li>; })}</ol> : <p className="list-empty">暂无执行事件，等待后端记录。</p>}
  </section>;
}
