import { useEffect, useRef, useState } from 'react';
import { ApiError } from '../../api.js';
import { AssistantDirectory, OriginalQuestion } from './live/AssistantQuestions.js';
import type { ResearchQuestion } from './live/assistantClient.js';
import { researchSessionsApi as api } from './researchSessionsClient.js';
import { draftKey, readStored, removeStored, requestKey, writeStored } from './researchSessionStorage.js';

type Draft = { assistantId: string; name: string; text: string };
type Pending = { requestId: string; assistantId: string };
type OriginalPayload = Pending & { text: string };
const errorText = (error: unknown) => error instanceof Error ? error.message : '请求尚未确认，请查询原问题。';
const notSent = new Set(['RESEARCH_ASSISTANT_UNCONFIGURED', 'LOCAL_BUDGET_EXHAUSTED', 'LOCAL_BUDGET_CLOSED_OR_EXPIRED', 'RESEARCH_QUESTION_REQUEST_CONFLICT', 'ASSISTANT_ENDPOINT_DISABLED']);
const collaborationReasons: Record<string, string> = {
  RESEARCH_SESSION_STOP_REQUESTED: '会话已请求停止，回复不会自动继续研究。',
  RESEARCH_TURN_LIMIT: '会话已达到轮次上限，无法自动开始下一轮。',
  RESEARCH_CONTEXT_LIMIT: '回复加入后超过上下文容量，无法继续；原问题仍保留。',
  RESEARCH_ASSISTANT_REPLY_UNAVAILABLE: '原回复尚不可用或已失去读权，请核对原问题与来源。',
  RESEARCH_SOURCE_UNAVAILABLE: '原共享来源已不可读，请核对来源权限。',
  RESEARCH_ORIGINAL_OUTCOME_UNCONFIRMED: '原研究执行结果尚未确认，请核对原任务；不会重复启动。',
  RESEARCH_COLLABORATION_ADMISSION_UNCONFIRMED: '自动继续请求尚未确认，请核对原问题与原任务；不会另建请求。',
  RESEARCH_COLLABORATION_CONTINUATION_NOT_INCLUDED: '自动继续轮在使用回答前已结束；查看原任务后，可自行决定是否手动继续，能否开始仍以会话当前可用操作为准。',
};

function QuestionStatus({ question }: { question: ResearchQuestion }) {
  const collaboration = question.collaboration;
  const labels = { waiting: `等待 ${question.recipientId} 的助手回答`, pending: '待纳入研究请求', included: '已纳入研究请求', blocked: '协作受阻', stopped: '已停止自动继续' };
  return <div className="rs-question-status">
    <span>{question.origin === 'agent' ? '助手自主提问' : '手动提问'} · 送达：{question.delivery.state} · {question.reply?.state === 'available' ? '回复已到' : question.reply ? '回答来源不可用' : '尚无回答'}</span>
    {collaboration && <p role="status">{labels[collaboration.state]}{collaboration.continuedTurnId && collaboration.state !== 'included' ? '；已保留自动继续轮次，尚未确认纳入。' : '。'}{collaboration.code && <>{collaborationReasons[collaboration.code] ?? '请核对原问题和原任务的实际状态。'}<small> {collaboration.code}</small></>}</p>}
  </div>;
}

export function SessionQuestions({ ownerId, sessionId, collaborationEnabled = false, questionId, onQuestion, onUse }: {
  ownerId: string; sessionId: string; collaborationEnabled?: boolean; questionId: string; onQuestion: (id: string) => void; onUse?: (id: string) => void;
}) {
  const draftStorage = `${draftKey(ownerId, sessionId)}:question`;
  const pendingStorage = `${requestKey(ownerId)}:question:${sessionId}`;
  const payloadStorage = `${draftStorage}:request`;
  const [draft, setDraft] = useState<Draft>(() => readStored(draftStorage, { assistantId: '', name: '', text: '' }));
  const [pending, setPending] = useState<Pending | null>(() => readStored(pendingStorage, null));
  const [payload, setPayload] = useState<OriginalPayload | null>(() => readStored(payloadStorage, null));
  const [notFound, setNotFound] = useState(false);
  const [saved, setSaved] = useState(true); const [open, setOpen] = useState(!!draft.text || !!pending);
  const [after, setAfter] = useState(''); const [refresh, setRefresh] = useState(0);
  const [page, setPage] = useState<{ items: ResearchQuestion[]; nextCursor: string | null } | null>(null);
  const [readError, setReadError] = useState(''); const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false); const lock = useRef(false); const active = useRef(false);
  const field = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  useEffect(() => {
    const controller = new AbortController(); setPage(null); setReadError('');
    let reading = false;
    async function read() {
      if (reading) return; reading = true;
      try {
        const value = await api.questions(ownerId, sessionId, after, '', controller.signal);
        if (!controller.signal.aborted) { setPage(value); setReadError(''); }
      } catch (reason) { if (!controller.signal.aborted) { setPage(null); setReadError(errorText(reason)); } }
      finally { reading = false; }
    }
    void read();
    const timer = window.setInterval(() => { if (document.visibilityState !== 'hidden') void read(); }, 4000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [ownerId, sessionId, after, refresh]);
  function change(value: Draft) { setDraft(value); setSaved(writeStored(draftStorage, value)); }
  function clearPending(original: Pending) {
    if (!active.current) return false;
    const stored = readStored<Pending | null>(pendingStorage, null);
    if (stored?.requestId !== original.requestId || stored.assistantId !== original.assistantId) return false;
    const savedPayload = readStored<OriginalPayload | null>(payloadStorage, null);
    if (savedPayload?.requestId === original.requestId && savedPayload.assistantId === original.assistantId) {
      removeStored(payloadStorage); setPayload(null);
    }
    removeStored(pendingStorage); setPending(null); return true;
  }
  function accept(value: ResearchQuestion, original: Pending) {
    if (value.sessionId !== sessionId || value.requestId !== original.requestId || value.assistantId !== original.assistantId) {
      throw new ApiError('原问题回执与会话不匹配，请继续核对。', 200, 'INVALID_RESPONSE');
    }
    if (!clearPending(original)) return;
    change({ ...draft, text: '' }); setOpen(false); setRefresh(value => value + 1);
    onQuestion(value.id); setNotice('原问题已保存。送达、回答和研究执行状态请分别核对。');
  }
  async function send() {
    if (lock.current || pending) return;
    if (!draft.assistantId || draft.text.trim().length < 2) {
      setError('请选择接收助手，并填写至少 2 个字的问题。'); field.current?.focus(); return;
    }
    const original = { requestId: crypto.randomUUID(), assistantId: draft.assistantId, text: draft.text.trim() };
    if (!writeStored(payloadStorage, original)) { setError('无法保存原发送文本，尚未发送。请保留输入并检查浏览器存储。'); return; }
    if (!writeStored(pendingStorage, { requestId: original.requestId, assistantId: original.assistantId })) {
      removeStored(payloadStorage); setError('无法保存原请求标识，尚未发送。请保留输入并检查浏览器存储。'); return;
    }
    setPayload(original); await transmit(original);
  }
  async function transmit(original: OriginalPayload) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setPending(original); setError(''); setNotice('');
    setNotFound(false);
    try { accept(await api.ask(ownerId, sessionId, original), original); }
    catch (reason) {
      if (reason instanceof ApiError && notSent.has(reason.code ?? '')) {
        clearPending(original);
      }
      if (active.current) { setError(errorText(reason)); setRefresh(value => value + 1); }
    } finally { lock.current = false; if (active.current) setBusy(false); }
  }
  async function recover() {
    if (!pending || lock.current) return;
    lock.current = true; setBusy(true); setError(''); setNotFound(false);
    try {
      const result = await api.questions(ownerId, sessionId, '', pending.requestId);
      if (result.items.length !== 1) throw new Error('尚未核对到唯一的原问题，不会重新发送。');
      accept(result.items[0], pending);
    } catch (reason) { if (active.current) {
      setError(errorText(reason));
      setNotFound(reason instanceof ApiError && reason.status === 404 && reason.code === 'RESEARCH_QUESTION_NOT_FOUND');
    } }
    finally { lock.current = false; if (active.current) setBusy(false); }
  }
  const originalPayload = pending && payload?.requestId === pending.requestId && payload.assistantId === pending.assistantId ? payload : null;
  const selectedQuestion = page?.items.find(question => question.id === questionId);
  return <section className="rs-questions" aria-label="本会话的同事问答">
    <h3>本会话的同事问答</h3><p>{collaborationEnabled ? '查看助手自主发出的问题、回复和采用状态，也可手动提问。手动提问的回复由你选择是否用于下一轮。' : '向一位同事的助手询问经验，回复回到这个会话；手动提问不会自动运行下一轮。'}</p>
    <div className="rw-actions"><button onClick={() => setOpen(value => !value)}>{open ? '收起提问（保留草稿）' : '向同事助手提问'}</button><button disabled={busy} onClick={() => setRefresh(value => value + 1)}>刷新已发问题</button></div>
    {open && <div className="rs-question-compose">
      {!draft.assistantId ? <AssistantDirectory ownerId={ownerId} onAsk={(assistantId, name) => change({ ...draft, assistantId, name })}/> : <p>接收助手：{draft.name || draft.assistantId} <button disabled={busy || !!pending} onClick={() => change({ ...draft, assistantId: '', name: '' })}>更换接收助手</button></p>}
      <form className="rw-form" noValidate onSubmit={event => { event.preventDefault(); void send(); }}><fieldset disabled={busy || !!pending}>
        <label>发给同事助手的问题<textarea ref={field} rows={3} maxLength={2000} value={draft.text} onChange={event => change({ ...draft, text: event.target.value })} aria-describedby={`rs-question-scope${error ? ' rs-question-error' : ''}`} aria-invalid={!!error}/></label>
        <p id="rs-question-scope" className="rw-muted">只发送这里的文本；会话目标、历史、文件和凭据不会自动附带。未发送内容保存在本浏览器，退出登录时清除。</p>
        <button className="rw-primary" disabled={!draft.assistantId}>{busy ? '正在发送…' : '确认发送问题'}</button>
      </fieldset></form>
    </div>}
    {error && <p id="rs-question-error" className="rw-error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {pending && <div className="rs-warning"><p>原问题请求仍待核对；不会自动重新发送，草稿继续保留。</p><button disabled={busy} onClick={() => void recover()}>查询原问题请求</button>{notFound && originalPayload && <><p>本次查询未找到原问题。再次提交会沿用原标识和原文本；若原问题已存在，只读取原结果。</p><button disabled={busy} onClick={() => void transmit(originalPayload)}>按原请求再次发送</button></>}{!originalPayload && <p>原发送文本已清除或不可恢复，目前只能核对原问题；不会用当前草稿或新标识替代。</p>}</div>}
    {!saved && <p className="rw-error" role="alert">浏览器无法保存草稿，离开前请复制当前问题。</p>}
    {readError ? <p className="rw-error" role="alert">{readError}</p> : !page ? <p role="status">正在读取已发问题…</p> : !page.items.length ? <p className="rw-muted">{after ? '本页没有已发问题。' : '还没有从这个会话发送问题。'}</p> : <ul className="rs-question-list">{page.items.map(question => <li key={question.id}><button aria-current={questionId === question.id ? 'true' : undefined} onClick={() => onQuestion(question.id)}>{question.text.length > 120 ? `${question.text.slice(0, 120)}…` : question.text}</button><QuestionStatus question={question}/></li>)}</ul>}
    <div className="rw-actions">{after && <button onClick={() => setAfter('')}>第一页问题</button>}{page?.nextCursor && <button onClick={() => setAfter(page.nextCursor!)}>下一页问题</button>}</div>
    {questionId && <div className="rs-original-question"><button onClick={() => onQuestion('')}>返回本会话问答</button>{readError ? <p role="status">暂时无法核对本会话的问题，原回复正文已隐藏；请刷新已发问题。</p> : selectedQuestion?.reply?.state === 'source_unavailable' ? <p role="status">原回复当前不可用，正文与来源已隐藏；请刷新已发问题核对。</p> : <OriginalQuestion key={`${ownerId}:${questionId}`} ownerId={ownerId} questionId={questionId} onUse={onUse}/>}</div>}
  </section>;
}
