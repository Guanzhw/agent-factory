import { useCallback, useEffect, useRef, useState } from 'react';
import { time } from '../../../workspaceUI.js';
import type { Page } from '../types.js';
import { assistantApi, type ResearchSource } from './assistantClient.js';
import { evidenceApi, type EvidenceEntry, type ResearchAssociation } from './evidenceClient.js';
const errorText = (error: unknown) => error instanceof Error ? error.message : '读取失败，请重新核对当前权限。';
function Source({ value }: { value: ResearchSource }) {
  return <article className="rw-source"><h3>原研究依据 · 尚未独立验证</h3><p className="rw-id">{value.id} · 作者 {value.ownerId}</p><pre>{JSON.stringify(value.source, null, 2)}</pre><pre>{JSON.stringify(value.content, null, 2)}</pre></article>;
}
export function EvidenceDirectory({ ownerId, kind, onSelect }: { ownerId: string; kind: 'associations'; onSelect: (id: string) => void }) {
  const [page, setPage] = useState<Page<EvidenceEntry> | null>(null); const [after, setAfter] = useState(''); const [refresh, setRefresh] = useState(0); const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController(); setPage(null); setError('');
    void evidenceApi[kind](ownerId, after, controller.signal).then(result => { if (!controller.signal.aborted) setPage(result); }).catch(reason => { if (!controller.signal.aborted) setError(errorText(reason)); });
    return () => controller.abort();
  }, [ownerId, kind, after, refresh]);
  const title = '相关研究关联';
  return <section className="rw-evidence" aria-label={title}><h2>{title}</h2><button onClick={() => setRefresh(count => count + 1)}>刷新{title}</button>{error && <p role="alert">{error}</p>}{!page && !error && <p role="status">正在读取…</p>}{page && !page.items.length && <p>本页没有当前可读的关联。</p>}{page?.items.map(item => <article className="rw-agreement" key={item.id}><p>作者：{item.ownerId} · {time(item.createdAt)}</p><button className="rw-id" onClick={() => onSelect(item.id)}>{item.id}</button></article>)}<div className="rw-actions">{after && <button onClick={() => setAfter('')}>返回目录第一页</button>}{page?.nextCursor && <button onClick={() => setAfter(page.nextCursor!)}>下一页{title}</button>}</div></section>;
}
export function AssociationDetail({ ownerId, id }: { ownerId: string; id: string }) {
  const [value, setValue] = useState<ResearchAssociation | null>(null); const [source, setSource] = useState<ResearchSource | null>(null); const [error, setError] = useState('');
  const active = useRef<AbortController | null>(null);
  const read = useCallback(async (sourceId?: string) => {
    active.current?.abort(); const controller = new AbortController(); active.current = controller;
    setValue(null); setSource(null); setError('');
    try {
      const result = await evidenceApi.association(ownerId, id, controller.signal);
      if (controller.signal.aborted) return;
      if (sourceId && [...result.sourceIds, ...result.inputContentIds].includes(sourceId)) {
        const original = await assistantApi.source(ownerId, sourceId, controller.signal);
        if (controller.signal.aborted) return;
        setSource(original);
      }
      setValue(result);
    } catch (reason) { if (!controller.signal.aborted) setError(errorText(reason)); }
  }, [ownerId, id]);
  useEffect(() => { const refresh = () => void read(); refresh(); window.addEventListener('focus', refresh); return () => { active.current?.abort(); window.removeEventListener('focus', refresh); }; }, [read]);
  return <section className="rw-evidence" aria-label="研究关联详情"><h2>研究关联 · Agent 分析</h2><button onClick={() => void read()}>核对关联与当前来源</button>{error && <p role="alert">{error} 旧关联正文与出处已隐藏。</p>}{value && <><p>作者：{value.ownerId} · {time(value.createdAt)}</p><p>关系：{value.analysis.relation} · 尚未独立验证</p><p className="rw-answer">{value.analysis.answer}</p><h3>原来源与全部输入依据</h3><p>来源可读不授权使用作者资源或修改其记录。</p>{[...new Set([...value.sourceIds, ...value.inputContentIds])].map(sourceId => <button className="rw-id" key={sourceId} onClick={() => void read(sourceId)}>{sourceId}</button>)}</>}{source && <Source value={source}/>}</section>;
}
