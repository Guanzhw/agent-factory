import { useCallback, useEffect, useRef, useState } from 'react';
import { useResearchCommand } from '../useProjectCommand.js';
import { assistantApi, type ResearchPeer, type ResearchQuestion, type ResearchSource } from './assistantClient.js';
import type { Page } from '../types.js';
const errorText = (error: unknown) => error instanceof Error ? error.message : '读取失败，请重新核对。';

export function AssistantDirectory({ ownerId, onAsk }: { ownerId: string; onAsk: (peer: string) => void }) {
  const [after, setAfter] = useState(''); const [page, setPage] = useState<Page<ResearchPeer> | null>(null);
  const [error, setError] = useState(''); const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setPage(null); setError('');
    void assistantApi.directory(ownerId, after, controller.signal).then(value => { if (!controller.signal.aborted) setPage(value); }).catch(reason => { if (!controller.signal.aborted) setError(errorText(reason)); });
    return () => controller.abort();
  }, [ownerId, after, refresh]);
  return <section aria-label="团队助手"><h2>向团队助手询问经验</h2><p>选择一位助手私密提问。回答只依据双方当前可读的团队研究记录，不自动启动训练。</p><button onClick={() => setRefresh(value => value + 1)}>刷新助手目录</button>
    {error && <p role="alert">{error}</p>}{!page && !error && <p role="status">正在读取助手…</p>}
    {page?.items.length === 0 && <p>本页尚无研究助手。</p>}{page?.items.map(peer => <article className="rw-agreement" key={peer.id}><h3>{peer.displayName}{peer.ownerId === ownerId ? '（我）' : ''}</h3><p>{peer.qaAvailable ? '可接收经验询问' : '当前未开放或操作额度不可用'}</p><button disabled={!peer.qaAvailable} onClick={() => onAsk(peer.id)}>向 {peer.displayName} 的助手提问</button></article>)}
    <div className="rw-actions">{after && <button onClick={() => setAfter('')}>第一页助手</button>}{page?.nextCursor && <button onClick={() => setAfter(page.nextCursor!)}>下一页助手</button>}</div>
  </section>;
}

export function AskAssistant({ ownerId, peerId, onQuestion }: { ownerId: string; peerId: string; onQuestion: (id: string) => void }) {
  const [text, setText] = useState('');
  const command = useResearchCommand<{ action: 'ask'; body: { requestId: string; text: string } }, ResearchQuestion>(`factory:research-question:${encodeURIComponent(ownerId)}:${encodeURIComponent(peerId)}`, ['ask'], value => assistantApi.ask(ownerId, peerId, value.body), result => onQuestion(result.id));
  return <form className="rw-form" aria-label="私密经验询问" onSubmit={event => { event.preventDefault(); void command.run({ action: 'ask', body: { requestId: crypto.randomUUID(), text: text.trim() } }); }}><h3>私密经验询问</h3><p className="rw-id">接收助手：{peerId}</p><p>只向这位助手发送，使用对方已确认的操作额度。token/费用未计量；不会因此获得训练或GPU权限。</p>{command.feedback}
    <fieldset disabled={command.disabled}><label>问题<textarea required minLength={2} maxLength={2000} value={text} onChange={event => setText(event.target.value)}/></label><button className="rw-primary" disabled={text.trim().length < 2}>发送私密问题</button></fieldset>
  </form>;
}

export function OriginalQuestion({ ownerId, questionId }: { ownerId: string; questionId: string }) {
  const [question, setQuestion] = useState<ResearchQuestion | null>(null);
  const [source, setSource] = useState<ResearchSource | null>(null);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const active = useRef<AbortController | null>(null);
  const read = useCallback(async (sourceId?: string) => {
    active.current?.abort(); const controller = new AbortController(); active.current = controller;
    setQuestion(null); setSource(null); setError(''); setBusy(true);
    try {
      const value = await assistantApi.question(ownerId, questionId, controller.signal);
      if (controller.signal.aborted) return;
      if (sourceId && value.reply?.state === 'available' && value.reply.contentIds.includes(sourceId)) {
        const result = await assistantApi.source(ownerId, sourceId, controller.signal);
        if (controller.signal.aborted) return;
        setSource(result);
      }
      setQuestion(value);
    } catch (reason) { if (!controller.signal.aborted) { setQuestion(null); setSource(null); setError(errorText(reason)); } }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }, [ownerId, questionId]);
  useEffect(() => {
    const refresh = () => void read();
    refresh(); window.addEventListener('focus', refresh);
    return () => { window.removeEventListener('focus', refresh); active.current?.abort(); };
  }, [read]);
  return <section aria-label="原私密问题"><h3>原私密问题</h3><p className="rw-id">问题：{questionId}</p><button onClick={() => void read()}>核对原问题</button>{busy && <p role="status">正在核对当前读权与回答…</p>}{error && <p role="alert">{error}</p>}
    {question && <><p>{question.text}</p><p>原回执：{question.delivery.state}</p><p className="rw-id">原任务：{question.delivery.taskId ?? '尚未确认'}</p>
      {!question.reply && <p>尚未取得回答。任务状态不代表已产生答案，请核对原问题。</p>}
      {question.reply?.state === 'source_unavailable' && <p role="status">输入依据已不可用；整个派生回答与依据已隐藏。</p>}
      {question.reply?.state === 'available' && <article className="rw-analysis"><h4>Agent 分析 · 尚未独立验证</h4><p className="rw-answer">{question.reply.text}</p><h4>输入依据</h4><p>包含模型实际读取的全部记录，不等于每条都被答案明确引用。</p>{question.reply.contentIds.length === 0 && <p>无可用团队依据；此回答不能视为有实验支持的结论。</p>}<ul>{question.reply.contentIds.map(id => <li key={id}><button className="rw-id" onClick={() => void read(id)}>{id}</button></li>)}</ul></article>}
    </>}
    {source && <article className="rw-source"><h4>原研究依据 · 尚未独立验证</h4><p className="rw-id">{source.id} · 作者 {source.ownerId}</p><pre>{JSON.stringify(source.source, null, 2)}</pre><pre>{JSON.stringify(source.content, null, 2)}</pre></article>}
  </section>;
}
