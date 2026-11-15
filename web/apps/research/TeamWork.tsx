import { useEffect, useRef, useState } from 'react';
import { ResearchReply } from './ResearchReply.js';
import { assistantApi, type ResearchPeer, type ResearchSource } from './live/assistantClient.js';
import { teamworkApi as api, type TeamWorkRecord } from './teamworkClient.js';

function SourceReference({ ownerId, id }: { ownerId: string; id: string }) {
  const [source, setSource] = useState<ResearchSource | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  async function read() {
    pending.current?.abort();
    const controller = new AbortController(); pending.current = controller;
    setSource(null); setError(''); setBusy(true);
    try { const value = await assistantApi.source(ownerId, id, controller.signal); if (!controller.signal.aborted) setSource(value); }
    catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '读取来源失败'); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <details className="rs-sources" onToggle={event => { if (event.currentTarget.open) void read(); else { pending.current?.abort(); setSource(null); } }}><summary>查看来源 {id}</summary>
    {busy && <p role="status">正在读取来源…</p>}{error && <p className="rw-error" role="alert">{error}</p>}
    {source && <article><p>作者 {source.ownerId} · 来源 {source.id} · {source.verificationStatus}</p><pre>{JSON.stringify(source.source, null, 2)}</pre><pre>{JSON.stringify(source.content, null, 2)}</pre></article>}
  </details>;
}

export function TeamWork({ ownerId, sessionId, open, onSession }: { ownerId: string; sessionId: string; open: boolean; onSession: (id: string) => void }) {
  const [items, setItems] = useState<TeamWorkRecord[]>([]);
  const [work, setWork] = useState<TeamWorkRecord | null>(null);
  const [selected, setSelected] = useState('');
  const [peers, setPeers] = useState<ResearchPeer[]>([]);
  const [after, setAfter] = useState('');
  const [next, setNext] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [title, setTitle] = useState('');
  const [goal, setGoal] = useState('');
  const [text, setText] = useState('');
  const [evidence, setEvidence] = useState('');
  const [assistantId, setAssistantId] = useState('');
  const [mode, setMode] = useState<'contribution' | 'request' | 'synthesis'>('contribution');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef({ signature: '', id: crypto.randomUUID() });
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    void (selected ? api.read(ownerId, selected, controller.signal).then(setWork) : api.list(ownerId, controller.signal).then(value => setItems(value.items)))
      .then(() => setError('')).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '读取失败'); });
    return () => controller.abort();
  }, [ownerId, open, selected, refresh]);
  useEffect(() => {
    if (!open || mode !== 'request') return;
    const controller = new AbortController();
    void assistantApi.directory(ownerId, after, controller.signal).then(page => {
      if (controller.signal.aborted) return;
      setPeers(current => after ? [...new Map([...current, ...page.items].map(peer => [peer.id, peer])).values()] : page.items);
      setNext(page.nextCursor);
    })
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '读取同事失败'); });
    return () => controller.abort();
  }, [ownerId, open, mode, after]);
  async function submit(create = false) {
    const signature = JSON.stringify({ create, selected, mode, title, goal, text, evidence, assistantId, sessionId });
    if (pending.current.signature !== signature) pending.current = { signature, id: crypto.randomUUID() };
    const requestId = pending.current.id;
    setBusy(true); setError('');
    try {
      const body = { requestId, text: text.trim(), evidenceIds: evidence.split(/[\s,，]+/).filter(Boolean) };
      const result = create ? await api.create(ownerId, { requestId, title: title.trim() || goal.trim().slice(0, 60), goal: goal.trim(), sessionId })
        : mode === 'request' ? await api.request(ownerId, selected, { requestId, text: body.text, assistantId, sessionId })
          : mode === 'synthesis' ? await api.synthesize(ownerId, selected, body)
            : await api.contribute(ownerId, selected, { ...body, sessionId });
      setWork(result); setSelected(result.id); setText(''); setEvidence(''); setTitle(''); setGoal(''); pending.current.signature = '';
    } catch (reason) { setError(reason instanceof Error ? reason.message : '操作未确认，请重试原请求'); }
    finally { setBusy(false); }
  }
  return <section aria-label="团队协作记录">
    <p>围绕共同目标，分享贡献并由牵头人整理结论。提交的文字与证据标识将进入团队记录。</p>
    <button type="button" disabled={busy} onClick={() => setRefresh(value => value + 1)}>刷新记录</button>
    {error && <p className="rw-error" role="alert">{error}</p>}
    {selected ? <>
      <button type="button" disabled={busy} onClick={() => { setSelected(''); setWork(null); setMode('contribution'); setText(''); setEvidence(''); }}>全部团队记录</button>
      {work ? <><h3>{work.title}</h3><ResearchReply text={work.goal}/><p>牵头人：{work.leadId}</p>{work.projectId && <p>关联项目：{work.projectId}</p>}
        {work.synthesis && <section aria-label="当前综合结论"><h4>综合结论</h4><ResearchReply text={work.synthesis.text}/></section>}
        {work.entries.map(entry => <article key={entry.id}><h4>{entry.kind === 'request' ? '询问同事助手' : entry.kind === 'synthesis' ? '牵头人综合' : '成员贡献'} · {entry.memberId}</h4><time>{new Date(entry.createdAt).toLocaleString()}</time><ResearchReply text={entry.text}/>
          {!!entry.evidenceIds.length && <p>证据：{entry.evidenceIds.join('、')}</p>}
          {entry.evidenceIds.map(id => <SourceReference key={id} ownerId={ownerId} id={id}/>)}
          {entry.origin && <details><summary>贡献来源</summary>
            {entry.origin.sessionId && <p>会话：{entry.origin.sessionId}{entry.memberId === ownerId && <button type="button" onClick={() => onSession(entry.origin!.sessionId!)}>打开我的原会话</button>}</p>}
            {entry.origin.turnId && <p>轮次：{entry.origin.turnId}</p>}
            {entry.origin.taskId && <p>任务：{entry.origin.taskId}</p>}
            {entry.origin.runId && <p>运行：{entry.origin.runId}</p>}
            {entry.origin.projectId && <p>项目：{entry.origin.projectId}</p>}
          </details>}
          {entry.recipientId && <p>接收助手：{entry.recipientId}</p>}
          {entry.delivery && <><p>请求状态：{entry.delivery.state}</p>{entry.delivery.taskId && <p>请求任务：{entry.delivery.taskId}</p>}{entry.delivery.runId && <p>请求运行：{entry.delivery.runId}</p>}</>}
          {entry.reply?.state === 'available' && <><h4>助手回复</h4><ResearchReply text={entry.reply.text}/>{!!entry.reply.contentIds.length && <p>回复来源：{entry.reply.contentIds.join('、')}</p>}{[...new Set([...entry.reply.contentIds, ...(entry.reply.citedContentIds ?? [])])].map(id => <SourceReference key={id} ownerId={ownerId} id={id}/>)}</>}
          {entry.reply?.state === 'source_unavailable' && <p role="status">回复来源当前不可用。</p>}
        </article>)}
        <form className="rw-form" onSubmit={event => { event.preventDefault(); void submit(); }}><fieldset disabled={busy}>
          <label>添加到团队记录<select value={mode} onChange={event => setMode(event.target.value as typeof mode)}><option value="contribution">分享贡献</option><option value="request">询问同事助手</option>{work.leadId === ownerId && <option value="synthesis">发布综合结论</option>}</select></label>
          {mode === 'request' && <><label>同事助手<select required value={assistantId} onChange={event => setAssistantId(event.target.value)}><option value="">选择助手</option>{peers.map(peer => <option key={peer.id} value={peer.id} disabled={!peer.qaAvailable}>{peer.displayName}{!peer.qaAvailable && '（不可用）'}</option>)}</select></label>{next && <button type="button" onClick={() => setAfter(next)}>更多同事</button>}<p>使用你当前的会话向所选助手发送这段问题。</p></>}
          <label>{mode === 'request' ? '问题' : mode === 'synthesis' ? '综合结论' : '贡献内容'}<textarea required value={text} onChange={event => setText(event.target.value)}/></label>
          {mode !== 'request' && <label>证据标识（可选，空格或逗号分隔）<input value={evidence} onChange={event => setEvidence(event.target.value)}/></label>}
          <button disabled={!text.trim() || mode === 'request' && !assistantId}>{busy ? '正在提交…' : '提交到团队记录'}</button>
        </fieldset></form></> : <p role="status">正在读取团队记录…</p>}
    </> : <><ul>{items.map(item => <li key={item.id}><button type="button" onClick={() => setSelected(item.id)}>{item.title}</button><span> · 牵头人 {item.leadId}</span></li>)}</ul>
      <details><summary>创建团队协作记录</summary><form className="rw-form" onSubmit={event => { event.preventDefault(); void submit(true); }}><fieldset disabled={busy}><label>共同目标<textarea required value={goal} onChange={event => setGoal(event.target.value)}/></label><label>名称（可选）<input value={title} onChange={event => setTitle(event.target.value)}/></label><button disabled={!goal.trim()}>创建团队记录</button></fieldset></form></details>
    </>}
  </section>;
}
