import { useCallback, useEffect, useRef, useState } from 'react';
import { time } from '../../../workspaceUI.js';
import { useResearchCommand } from '../useProjectCommand.js';
import type { Page } from '../types.js';
import { assistantApi, type ResearchSource } from './assistantClient.js';
import { downloadResearchDelivery, evidenceApi, type EvidenceEntry, type ResearchAssociation, type ResearchDelivery } from './evidenceClient.js';
const errorText = (error: unknown) => error instanceof Error ? error.message : '读取失败，请重新核对当前权限。';
function Source({ value }: { value: ResearchSource }) {
  return <article className="rw-source"><h3>原研究依据 · 尚未独立验证</h3><p className="rw-id">{value.id} · 作者 {value.ownerId}</p><pre>{JSON.stringify(value.source, null, 2)}</pre><pre>{JSON.stringify(value.content, null, 2)}</pre></article>;
}
export function EvidenceDirectory({ ownerId, kind, onSelect }: { ownerId: string; kind: 'associations' | 'deliveries'; onSelect: (id: string) => void }) {
  const [page, setPage] = useState<Page<EvidenceEntry> | null>(null); const [after, setAfter] = useState(''); const [refresh, setRefresh] = useState(0); const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController(); setPage(null); setError('');
    void evidenceApi[kind](ownerId, after, controller.signal).then(result => { if (!controller.signal.aborted) setPage(result); }).catch(reason => { if (!controller.signal.aborted) setError(errorText(reason)); });
    return () => controller.abort();
  }, [ownerId, kind, after, refresh]);
  const title = kind === 'associations' ? '相关研究关联' : '可读研究成果';
  return <section className="rw-evidence" aria-label={title}><h2>{title}</h2><button onClick={() => setRefresh(count => count + 1)}>刷新{title}</button>{error && <p role="alert">{error}</p>}{!page && !error && <p role="status">正在读取…</p>}{page && !page.items.length && <p>本页没有当前可读的{kind === 'associations' ? '关联' : '成果'}。</p>}{page?.items.map(item => <article className="rw-agreement" key={item.id}><p>作者：{item.ownerId} · {time(item.createdAt)}</p><button className="rw-id" onClick={() => onSelect(item.id)}>{item.id}</button></article>)}<div className="rw-actions">{after && <button onClick={() => setAfter('')}>返回目录第一页</button>}{page?.nextCursor && <button onClick={() => setAfter(page.nextCursor!)}>下一页{title}</button>}</div></section>;
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
export function CreateDelivery({ ownerId, projectId, version, onCreated }: { ownerId: string; projectId: string; version: number; onCreated: (id: string) => void }) {
  const command = useResearchCommand<{ action: 'delivery'; body: { requestId: string; expectedVersion: number } }, ResearchDelivery>(`factory:research-delivery:${encodeURIComponent(ownerId)}:${encodeURIComponent(projectId)}`, ['delivery'], value => evidenceApi.create(ownerId, projectId, value.body), value => onCreated(value.id));
  return <section><h3>生成当前成果修订</h3><p>按目标版本 {version} 汇集原记录；未终态、缺配方或未提供剩余问题都将明确保留，不会启动实验。</p>{command.feedback}<button disabled={command.disabled} onClick={() => void command.run({ action: 'delivery', body: { requestId: crypto.randomUUID(), expectedVersion: version } })}>生成成果清单</button></section>;
}
export function DeliveryDetail({ ownerId, id }: { ownerId: string; id: string }) {
  const [value, setValue] = useState<ResearchDelivery | null>(null); const [source, setSource] = useState<ResearchSource | null>(null); const [error, setError] = useState(''); const [busy, setBusy] = useState(false); const [saved, setSaved] = useState(false);
  const active = useRef<AbortController | null>(null);
  const read = useCallback(async (sourceId?: string, download = false) => {
    active.current?.abort(); const controller = new AbortController(); active.current = controller;
    setValue(null); setSource(null); setError(''); setSaved(false); setBusy(true);
    try {
      const result = await evidenceApi.delivery(ownerId, id, controller.signal);
      if (controller.signal.aborted) return;
      if (sourceId && result.sourceIds.includes(sourceId)) {
        const original = await assistantApi.source(ownerId, sourceId, controller.signal);
        if (controller.signal.aborted) return;
        setSource(original);
      }
      if (download) {
        const blob = await downloadResearchDelivery(ownerId, id, controller.signal);
        if (controller.signal.aborted) return;
        const url = URL.createObjectURL(blob);
        try { const link = document.createElement('a'); link.href = url; link.download = 'research-delivery.zip'; document.body.append(link); link.click(); link.remove(); } finally { URL.revokeObjectURL(url); }
        setSaved(true);
      }
      setValue(result);
    } catch (reason) { if (!controller.signal.aborted) setError(errorText(reason)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }, [ownerId, id]);
  useEffect(() => { const refresh = () => void read(); refresh(); window.addEventListener('focus', refresh); return () => { active.current?.abort(); window.removeEventListener('focus', refresh); }; }, [read]);
  return <section className="rw-evidence" aria-label="研究成果详情"><h2>研究成果清单</h2><button onClick={() => void read()}>核对成果与当前来源</button>{busy && <p role="status">正在读取当前授权成果…</p>}{error && <p role="alert">{error} 旧成果正文与下载已隐藏。</p>}{saved && <p role="status">已交给浏览器下载；未声明独立哈希校验或科学复现通过。</p>}{value && <><p>作者：{value.ownerId} · {time(value.createdAt)}</p><p className="rw-id">项目：{value.projectId} · 目标版本 {value.goalVersion}</p><h3>{value.missingEvidence.length ? '成果不完整' : '已收集选中证据 · 尚未独立验证'}</h3>{value.missingEvidence.length > 0 && <ul>{value.missingEvidence.map(item => <li key={item}>{item}</li>)}</ul>}{value.ending ? <section><h3>结束依据与剩余问题（原文）</h3>
      <p>项目所有者：{value.ending.ownerId} · 目标版本 {value.ending.goalVersion} · {time(value.ending.endedAt)}</p>
      <p>原结束结论：{value.ending.outcome} · 尚未独立验证</p><p className="rw-answer">{value.ending.reason}</p>
      <p>资源清理：{value.ending.resourceCleanup === 'not_observed' ? '未确认资源停止' : value.ending.resourceCleanup}</p>
      <p>未单独整理剩余问题；请参阅上述原结束记录。</p></section> : <p>没有结束快照；剩余问题尚未提供独立记录，不代表没有疑问。</p>}<p>{value.evidenceFormat}</p><p>{value.continuation}</p><button disabled={busy} onClick={() => void read(undefined, true)}>下载当前授权成果包</button><h3>原记录与负结果</h3>{value.records.map((record, index) => <details key={value.recordIds[index]}><summary>原记录 {value.recordIds[index]}</summary><pre>{JSON.stringify(record, null, 2)}</pre></details>)}<h3>完整来源</h3>{value.sourceIds.map(sourceId => <button className="rw-id" key={sourceId} onClick={() => void read(sourceId)}>{sourceId}</button>)}</>}{source && <Source value={source}/>}</section>;
}
