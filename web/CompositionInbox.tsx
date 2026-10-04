import { useEffect, useRef, useState } from 'react';
import { CompositionInboxRequests, type CompositionInboxPage } from './compositionInboxState.js';

export interface CompositionInboxProps {
  ownerId: string;
  loadPage: (after?: string, signal?: AbortSignal) => Promise<unknown>;
  onSelect: (proposalId: string) => void;
  disabled?: boolean;
  refreshKey?: string | number;
}
const labels = { pending: '等待决定', revised: '已有修订', rejected: '已拒绝', accepted: '已固定方案' };
export function CompositionInboxList({ page, onSelect, disabled = false }: { page: CompositionInboxPage; onSelect: (id: string) => void; disabled?: boolean }) {
  return <div className="task-list-items">{page.items.map(item => <article className="material-row" style={{ gridTemplateColumns: 'minmax(0, 1fr)' }} key={item.id}>
    <div className="material-info" style={{ minWidth: 0, overflowWrap: 'anywhere' }}><h3>{item.goalPreview}</h3>
      <p><span className="badge">{labels[item.state]}</span> · {item.preflightStatus === 'ready' ? '原提案预检通过' : '原提案存在缺项'}</p>
      <p className="quiet">{item.applicationRef.id} · v{item.applicationRef.version} · {item.mode}</p>
      <p className="quiet">{new Date(item.createdAt).toLocaleString('zh-CN')}</p>
      {item.parentId && <p className="quiet">此提案保留原修订关系。</p>}
      <button className="secondary" disabled={disabled} onClick={() => onSelect(item.id)}>{item.state === 'accepted' ? '查看原方案' : '恢复此提案'}</button>
    </div>
  </article>)}</div>;
}

export function CompositionInbox({ ownerId, loadPage, onSelect, disabled = false, refreshKey }: CompositionInboxProps) {
  const [after, setAfter] = useState<string>();
  const [refresh, setRefresh] = useState(0);
  const [known, setKnown] = useState<{ owner: string; page: CompositionInboxPage }>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const requests = useRef(new CompositionInboxRequests());
  const loader = useRef(loadPage); loader.current = loadPage;
  const previousOwner = useRef(ownerId);
  const page = known?.owner === ownerId ? known.page : undefined;
  useEffect(() => {
    const controller = new AbortController();
    const changedOwner = previousOwner.current !== ownerId;
    previousOwner.current = ownerId;
    if (changedOwner) setAfter(undefined);
    setLoading(true); setError('');
    const cursor = changedOwner ? undefined : after;
    void requests.current.load(ownerId, cursor, loader.current, controller.signal).then(next => {
      if (next) setKnown({ owner: ownerId, page: next });
    }).catch(() => {
      if (!controller.signal.aborted) setError('暂时无法读取提案。保留上次已核对的列表；状态可能已变化。');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    const current = requests.current;
    return () => { controller.abort(); current.invalidate(); };
  }, [ownerId, after, refresh, refreshKey]);
  const firstPage = () => { setAfter(undefined); setRefresh(value => value + 1); };
  return <section className="task-list" aria-label="我的装配提案">
    <div className="section-heading"><h2>我的装配提案</h2><button className="text-button" disabled={disabled || loading} onClick={firstPage}>重新读取第一页</button></div>
    <p className="quiet">找回已保存的提案或原方案。查看记录不会接受提案、开始任务或恢复已撤回的权限。</p>
    {error && <div className="error-message" role="alert"><span>{error}</span><button className="text-button" disabled={disabled || loading} onClick={() => setRefresh(value => value + 1)}>重试读取</button></div>}
    {loading && <p className="quiet" role="status">正在读取装配记录…</p>}
    {page && <CompositionInboxList page={page} onSelect={id => { if (!disabled && !loading && known?.owner === ownerId) onSelect(id); }} disabled={disabled || loading}/>}
    {!loading && !error && page?.items.length === 0 && <p className="list-empty">当前页没有已保存的装配提案。</p>}
    {page && <p className="quiet">当前页 {page.items.length} 条；这是分页读取，状态可能更新，不是完整实时快照。</p>}
    <div className="button-row">{after && <button className="secondary" disabled={disabled || loading} onClick={firstPage}>返回第一页</button>}
      {page?.nextCursor && <button className="secondary" disabled={disabled || loading || !!error} onClick={() => setAfter(page.nextCursor!)}>查看下一页</button>}</div>
  </section>;
}
