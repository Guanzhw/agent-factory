import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../../api.js';
import { assistantApi, type ResearchSource } from './live/assistantClient.js';
import { researchSessionsApi as api, type CreateSession, type ResearchSession, type SessionAction, type SessionOptions, type SessionPage, type SessionTurn } from './researchSessionsClient.js';
import { draftKey, readStored, removeStored, requestKey, writeStored, type PendingSessionRequest, type SessionDraft } from './researchSessionStorage.js';
import { SessionQuestions } from './SessionQuestions.js';
import './sessions.css';

type Props = { ownerId: string; selectedId?: string; questionId?: string; onSelect: (id: string) => void; onQuestion: (id: string) => void; onModels: () => void; onTask: (id: string) => void };
const states = { idle: '就绪', running: '执行中', stopping: '停止请求已接收', stopped: '已停止', blocked: '需要核对' };
const reasons: Record<string, string> = {
  RESEARCH_CONTEXT_LIMIT: '必要上下文超过容量，不能开始新一轮；目标、指令及原操作记录不会被截断，完整历史仍保留。',
  RESEARCH_SUMMARY_INPUT_LIMIT: '待整理的回复超过单次整理容量，本会话不能开始新一轮；完整历史仍可查看。',
  RESEARCH_SOURCE_UNAVAILABLE: '已引用的共享来源当前不可访问，需要核对发布状态或权限。',
  RESEARCH_ASSISTANT_REPLY_UNAVAILABLE: '已采用的同事回复或来源当前不可读，正文已隐藏；请核对原问题与共享权限。',
  RESEARCH_RESTART_REQUIRES_RECONCILIATION: '重启前的工具操作需要核对，不能自动重放。',
  RESEARCH_EFFECT_UNCONFIRMED: '原工具操作的结果尚未确认。',
  RESEARCH_ORIGINAL_OUTCOME_UNCONFIRMED: '原执行结果未知，需要核对原任务。',
  RESEARCH_QUEUE_IDENTITY_UNCONFIRMED: '原执行身份无法核实，已阻止新的模型调用。',
  RESEARCH_QUEUE_ATTEMPT_UNCONFIRMED: '原执行尝试无法核实，已阻止新的模型调用。',
  RESEARCH_WORKSPACE_UNCONFIGURED: '尚未配置会话工作目录，请联系维护者启用。',
  RESEARCH_COMMANDS_DISABLED: '本地命令执行尚未启用，请联系维护者核对。',
  RESEARCH_TOOLS_UNAVAILABLE: '研究工具未就绪，请联系维护者核对。',
  RESEARCH_MODEL_REQUIRED: '尚无可用模型，请先配置自己的模型。',
};
const actions: Record<SessionAction, string> = { create: '创建会话', turn: '开始一轮', correct: '补充纠正', stop: '请求停止' };
const describe = (error: unknown) => error instanceof Error ? error.message : '操作未确认，请核对原请求。';
const time = (value: string) => new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const unresolved = (error: unknown) => !(error instanceof ApiError) || ![400, 401, 403, 404, 422].includes(error.status) || error.code === 'INVALID_RESPONSE';
const initialDraft: SessionDraft = { title: '', goal: '', boundaries: '', modelConnectionRef: '', limits: { maxTurns: 8, toolCallsPerTurn: 8, operationSeconds: 8 } };

function useDraft<T>(key: string, fallback: T) {
  const [value, setValue] = useState<T>(() => readStored(key, fallback));
  const [saved, setSaved] = useState(true);
  function change(next: T) { setValue(next); setSaved(writeStored(key, next)); }
  return { value, change, saved };
}

function CreateSessionForm({ ownerId, options, busy, blocked, onModels, onCreate }: { ownerId: string; options: SessionOptions | null; busy: boolean; blocked: boolean; onModels: () => void; onCreate: (value: Omit<CreateSession, 'requestId'>) => void }) {
  const draft = useDraft(draftKey(ownerId), initialDraft);
  const initialized = useRef(readStored(draftKey(ownerId), null) !== null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const form = useRef<HTMLFormElement | null>(null);
  const value = draft.value;
  useEffect(() => {
    const invalid = form.current?.querySelector<HTMLElement>('[aria-invalid="true"]');
    if (!invalid) return;
    const disclosure = invalid.closest('details');
    if (disclosure) disclosure.open = true;
    invalid.focus({ preventScroll: true });
    invalid.closest('label')?.scrollIntoView?.({ block: 'center' });
  }, [errors]);
  useEffect(() => {
    if (!options || initialized.current) return;
    initialized.current = true;
    if (readStored(draftKey(ownerId), null) !== null) return;
    draft.change({ ...initialDraft, modelConnectionRef: options.models.find(model => model.available)?.connectionRef ?? '', limits: {
      maxTurns: options.limits.maxTurns.default, toolCallsPerTurn: options.limits.toolCallsPerTurn.default, operationSeconds: options.limits.operationSeconds.default,
    } });
    // Options initialize a new draft once; rereads must not overwrite an edited field.
  }, [options, ownerId]);
  function submit() {
    const problems: Record<string, string> = {};
    if (!value.title.trim()) problems.title = '给会话起一个名称，方便之后继续。';
    if (value.goal.trim().length < 2) problems.goal = '请描述要研究或完成的目标，至少 2 个字。';
    if (!value.boundaries.trim()) problems.boundaries = '请说明何时停止，或哪些操作不能进行。';
    if (!options?.models.some(model => model.available && model.connectionRef === value.modelConnectionRef)) problems.model = '请选择当前可用的模型连接。';
    if (options) for (const key of ['maxTurns', 'toolCallsPerTurn', 'operationSeconds'] as const) {
      const limit = options.limits[key];
      if (!Number.isInteger(value.limits[key]) || value.limits[key] < limit.min || value.limits[key] > limit.max) problems[key] = `请输入 ${limit.min}–${limit.max} 之间的整数。`;
    }
    setErrors(problems);
    if (!Object.keys(problems).length) onCreate({ ...value, title: value.title.trim(), goal: value.goal.trim(), boundaries: value.boundaries.trim() });
  }
  return <section className="rs-create"><h2>从一个研究目标开始</h2><p className="rw-muted">同一会话保留目标、边界和每轮记录。打开或刷新页面只读取记录。</p>
    {options?.collaboration?.available && <p className="rs-collaboration-note">助手可按研究目标自主询问已开放的同事助手，只发送所需的问题文本。收到回复后可在原限制内继续；你可以随时请求停止，不必逐条确认问答。</p>}
    <form ref={form} className="rw-form" noValidate onSubmit={event => { event.preventDefault(); submit(); }}><fieldset disabled={busy || blocked}>
      <label>会话名称<input maxLength={120} value={value.title} onChange={event => draft.change({ ...value, title: event.target.value })} aria-invalid={!!errors.title}/>{errors.title && <span role="alert">{errors.title}</span>}</label>
      <label>研究目标<textarea rows={4} maxLength={2000} value={value.goal} onChange={event => draft.change({ ...value, goal: event.target.value })} aria-invalid={!!errors.goal}/>{errors.goal && <span role="alert">{errors.goal}</span>}</label>
      <label>停止边界<textarea rows={2} maxLength={2000} value={value.boundaries} onChange={event => draft.change({ ...value, boundaries: event.target.value })} aria-invalid={!!errors.boundaries}/><small>写明达标条件、禁止事项或需要先问你的情况。这是给助手的指令；下面的调用次数和时限由系统限制。</small>{errors.boundaries && <span role="alert">{errors.boundaries}</span>}</label>
      <label>使用模型<select value={value.modelConnectionRef} onChange={event => draft.change({ ...value, modelConnectionRef: event.target.value })} aria-invalid={!!errors.model}><option value="">选择模型连接</option>{options?.models.map(model => <option key={model.connectionRef} value={model.connectionRef} disabled={!model.available}>{model.provider} · {model.model}{!model.available ? '（不可用）' : ''}</option>)}</select>{errors.model && <span role="alert">{errors.model}</span>}</label>
      <button type="button" className="rs-text-button" onClick={onModels}>配置我的模型</button>
      <details className="rs-limits"><summary>调用次数与操作时限</summary><div className="rs-limit-grid">{([['maxTurns', '会话最多轮次'], ['toolCallsPerTurn', '每轮最多工具调用'], ['operationSeconds', '单次操作时限（秒）']] as const).map(([key, label]) => <label key={key}>{label}<input type="number" min={options?.limits[key].min ?? 1} max={options?.limits[key].max} value={value.limits[key]} onChange={event => draft.change({ ...value, limits: { ...value.limits, [key]: Number(event.target.value) } })} aria-invalid={!!errors[key]}/>{options && <small>范围 {options.limits[key].min}–{options.limits[key].max}</small>}{errors[key] && <span role="alert">{errors[key]}</span>}</label>)}</div></details>
      {options ? <p className="rw-muted">未提供 token 或费用计量。{options.workspace.configured ? '文件和命令使用服务配置的本机会话目录；目录限制不等同于操作系统沙箱。' : '服务尚未配置会话工作目录，需要维护者启用后才能执行。'}</p> : <p role="status">正在读取模型与执行环境…</p>}
      {!options?.available && options && <p className="rw-error" role="alert">当前无法开始：{reasons[options.unavailableCode ?? ''] ?? options.unavailableCode ?? '研究环境不可用'}<small> {options.unavailableCode}</small></p>}
      <button className="rw-primary" disabled={!options?.available}>{busy ? '正在保存并开始…' : '创建并开始研究'}</button>
    </fieldset></form>{!draft.saved && <p className="rw-error" role="alert">浏览器无法保存草稿；离开前请复制当前输入。</p>}
  </section>;
}

function ToolOutput({ result }: { result: Record<string, unknown> }) {
  const output = result.output && typeof result.output === 'object' && !Array.isArray(result.output) ? result.output as Record<string, unknown> : null;
  if (output && Array.isArray(output.argv) && output.argv.every(item => typeof item === 'string')) return <div className="rs-command-output"><p><strong>命令</strong> <code>{output.argv.join(' ')}</code></p><p>工作目录：{String(output.cwd ?? '')} · 退出码：{typeof output.exitCode === 'number' ? output.exitCode : '未确认'}</p>{typeof output.stdout === 'string' && output.stdout && <><h4>标准输出</h4><pre>{output.stdout}</pre></>}{typeof output.stderr === 'string' && output.stderr && <><h4>错误输出</h4><pre>{output.stderr}</pre></>}<details><summary>原工具回执</summary><pre>{JSON.stringify(result, null, 2)}</pre></details></div>;
  if (output && typeof output.path === 'string' && typeof output.afterSha256 === 'string') return <div><p><strong>{output.created === true ? '新建文件' : '修改文件'}</strong> <code>{output.path}</code></p><p>修改前：<code>{String(output.beforeSha256 ?? '文件不存在')}</code></p><p>修改后：<code>{output.afterSha256}</code></p><details><summary>原工具回执</summary><pre>{JSON.stringify(result, null, 2)}</pre></details></div>;
  return <pre>{JSON.stringify(result, null, 2)}</pre>;
}

function TurnRecord({ turn, onTask, onQuestion }: { turn: SessionTurn; onTask: (id: string) => void; onQuestion: (id: string) => void }) {
  const replies = [...(turn.assistantReply ? [turn.assistantReply] : []), ...(turn.assistantReplies ?? [])];
  return <article className="rs-turn"><header><h3>第 {turn.sequence} 轮</h3><span>{turn.status}</span><time>{time(turn.createdAt)}</time></header>
    {turn.continuation && <div className="rs-continuation"><p>由同事回复自动发起本轮。创建轮次不代表回复已纳入模型请求，请核对下方引用与原问题状态。</p>{turn.continuation.questionIds.map(id => <button key={id} className="rs-text-button" onClick={() => onQuestion(id)}>自动继续的原问题 {id}</button>)}</div>}
    {turn.messages.map(message => <div key={message.id} className={`rs-message rs-${message.kind}`}><div className="rs-message-heading"><strong>{message.kind === 'correction' ? '你的纠正' : turn.continuation ? '自动继续指令' : '你的指令'}</strong><span>{message.state === 'included' ? '已纳入研究请求' : '待纳入研究请求'}</span></div><p>{message.text}</p></div>)}
    {turn.result !== null && <div className="rs-message rs-reply"><strong>助手回复</strong><p>{turn.result}</p></div>}
    {!!replies.length && <section className="rs-adopted-reply" aria-label={`第 ${turn.sequence} 轮引用的同事回复`}><h4>本轮引用的同事回复</h4>{replies.map(reply => <div key={reply.questionId}><button className="rs-text-button" onClick={() => onQuestion(reply.questionId)}>核对原问题 {reply.questionId}</button>{reply.state === 'available' ? <><p>{reply.questionText}</p><p>{reply.reply.text}</p><p className="rw-muted">作为引用证据，不代表实验已验证。输入依据：{reply.reply.contentIds.length ? reply.reply.contentIds.join('、') : '无可用团队依据'}</p></> : <p role="status">引用的回复当前不可用，正文与来源已隐藏；后续研究需先核对权限。</p>}</div>)}</section>}
    {turn.failure && <p className="rw-error" role="alert">本轮未完成：{turn.failure}</p>}
    {!!turn.toolResults.length && <section className="rs-tool-results" aria-label={`第 ${turn.sequence} 轮工具结果`}><h4>工具与文件记录</h4>{turn.toolResults.map(item => <details key={item.effectKey} open={item.status.toUpperCase() === 'UNKNOWN'}><summary><span>{item.status.toUpperCase() === 'UNKNOWN' ? '结果未知，需核对原操作' : `工具回执：${item.status}`}</span><code>{item.effectKey}</code></summary>{item.result ? <ToolOutput result={item.result}/> : <p>还没有已确认的结果。</p>}</details>)}</section>}
    <details className="rs-events" open={turn.events.some(event => event.data.outcome === 'unknown' || event.type === 'research_reconciliation_required')}><summary>执行事件 · {turn.events.length} 条</summary><p className="rw-muted">以下是已保存的任务事件，不是模型全文流。</p>{turn.events.length ? <ol>{turn.events.map(event => <li key={event.id}><time>{time(event.createdAt)}</time><strong>{event.type}</strong><p>{event.message}</p>{Object.keys(event.data).length > 0 && <details><summary>事件详情</summary><pre>{JSON.stringify(event.data, null, 2)}</pre></details>}</li>)}</ol> : <p>还没有任务事件。</p>}</details>
    {turn.taskId && <button className="rs-text-button" onClick={() => onTask(turn.taskId!)}>查看原任务记录</button>}
  </article>;
}

function SharedSources({ ownerId, ids }: { ownerId: string; ids: string[] }) {
  const [source, setSource] = useState<ResearchSource | null>(null); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  async function read(id: string) {
    pending.current?.abort(); const controller = new AbortController(); pending.current = controller;
    setSource(null); setError(''); setBusy(true);
    try { const value = await assistantApi.source(ownerId, id, controller.signal); if (!controller.signal.aborted) setSource(value); }
    catch (reason) { if (!controller.signal.aborted) setError(describe(reason)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <details className="rs-sources"><summary>已引用的共享来源 · {ids.length}</summary><p>仅包含同事明确发布的研究证据。每次查看都重新核对当前权限。</p>{ids.map(id => <button key={id} disabled={busy} onClick={() => void read(id)}>{id}</button>)}{!ids.length && <p className="rw-muted">尚未引用共享证据。</p>}{busy && <p role="status">正在核对来源…</p>}{error && <p className="rw-error" role="alert">{error} 原来源正文已隐藏。</p>}{source && <article><h3>原共享证据 · {source.verificationStatus}</h3><p>作者 {source.ownerId} · 来源 {source.id}</p><pre>{JSON.stringify(source.source, null, 2)}</pre><pre>{JSON.stringify(source.content, null, 2)}</pre></article>}</details>;
}

function ContextStatus({ value, blocked }: { value: ResearchSession; blocked: boolean }) {
  const summary = value.context.compaction;
  if (!summary) return null;
  const canStart = value.allowedActions.includes('start') && !blocked;
  const titles = { needed: '继续前需要整理上下文', preparing: '正在整理上下文', ready: '上下文已整理', failed: '上下文整理未完成', unknown: '整理结果尚未确认' };
  return <section className={`rs-context-status${['failed', 'unknown'].includes(summary.status) ? ' rs-warning' : ''}`} role="status" aria-live="polite" aria-atomic="true" aria-label="上下文整理状态">
    <h3>{titles[summary.status]}</h3>
    {summary.status === 'needed' && <p>{canStart ? '填写下一轮指令并点击“开始这一轮”后，会先整理早期助手回复，再继续研究。打开或刷新不会执行。' : '早期助手回复需要整理；当前不能开始新一轮，请先核对会话状态和原任务记录。'}</p>}
    {summary.status === 'preparing' && <p>正在为这一轮准备摘要，尚未进入研究请求。整理完成不代表你的纠正已被纳入。</p>}
    {summary.status === 'ready' && <p>后续研究将使用已确认的摘要；目标、停止边界、你的原始指令和操作状态仍单独保留。</p>}
    {summary.status === 'failed' && <p>本轮未能保存可用摘要，没有据此继续研究。{canStart ? '你可以填写下一轮指令并明确开始，再尝试整理。' : '当前不能开始新一轮，请先核对会话状态和原任务记录。'}</p>}
    {summary.status === 'unknown' && <p>上次整理请求没有确认结果，不会自动重发。{canStart ? '填写下一轮指令并明确开始，可能新增一次用于整理的模型请求。' : '当前不能开始新一轮，请先核对会话状态和原任务记录。'}</p>}
    <p>{summary.throughSequence > 0 ? `${summary.status === 'ready' ? '已确认的摘要覆盖至' : '上次已确认的摘要覆盖至'}第 ${summary.throughSequence} 轮。` : '尚无已确认的摘要。'} 完整研究记录仍保留在上方。</p>
    {summary.code && <p className="rs-context-code">原因代码：<code>{summary.code}</code></p>}
  </section>;
}

function SessionDetail({ ownerId, value, busy, blocked, questionId, onQuestion, onSend, onStop, onTask }: { ownerId: string; value: ResearchSession; busy: boolean; blocked: boolean; questionId: string; onQuestion: (id: string) => void; onSend: (text: string, correction: boolean, assistantQuestionId?: string) => Promise<boolean>; onStop: () => void; onTask: (id: string) => void }) {
  const draft = useDraft(draftKey(ownerId, value.id), ''); const [error, setError] = useState('');
  const selectedReply = useDraft(`${draftKey(ownerId, value.id)}:reply`, '');
  const composer = useRef<HTMLTextAreaElement | null>(null);
  const correction = value.state === 'running' && value.allowedActions.includes('correct');
  const stateLabel = value.state === 'idle' ? value.turns.length ? value.allowedActions.includes('start') ? '可继续' : '本轮已结束' : '待开始' : states[value.state];
  async function send() {
    if (!draft.value.trim()) { setError('请填写这一轮要做的事，或要补充的限制。'); return; }
    setError(''); if (await onSend(draft.value.trim(), correction, !correction && selectedReply.value || undefined)) { draft.change(''); if (!correction) selectedReply.change(''); }
  }
  return <section className="rs-detail" aria-label="研究会话详情"><header className="rs-detail-heading"><div><h2>{value.title}</h2><span className={`rs-state rs-state-${value.state}`}>{stateLabel}</span></div>{value.allowedActions.includes('stop') && <button disabled={busy} onClick={onStop}>请求停止</button>}</header>
    {value.state === 'stopping' && <p className="rs-warning" role="status">已记录停止请求，仍在等待执行边界和本地进程的停止回执；目前不能确认已停止。</p>}
    {value.collaboration?.enabled ? <p className="rs-collaboration-note">{value.state === 'stopped' ? '会话已停止，之后到达的同事回复不会自动继续研究。原问题仍可核对；停止本会话不会停止同事的任务。' : '此会话可自主询问同事助手，收到回复后按原限制继续。请求停止会取消尚未采用的自动继续安排，不会停止同事的任务。'}</p> : <p className="rw-muted">此会话沿用原配置，仅支持手动向同事助手提问；自主协作仅用于具备该能力的新会话。</p>}
    {value.state === 'blocked' && <p className="rw-error" role="alert">本会话不能开始新一轮：{reasons[value.blockReason ?? ''] ?? '原操作需要核对。'} 历史和原任务记录仍可查看，不会自动重放。<code>{value.blockReason}</code></p>}
    <details className="rs-agreement"><summary>目标、停止边界与模型</summary><h3>研究目标</h3><p>{value.goal}</p><h3>停止边界</h3><p>{value.boundaries}</p><p>{value.model.provider} · {value.model.model}</p><p>最多 {value.limits.maxTurns} 轮 · 每轮最多 {value.limits.toolCallsPerTurn} 次工具调用 · 单次操作 {value.limits.operationSeconds} 秒</p><p>当前会话上下文 {value.context.characters} / {value.context.maximumCharacters} 字符。{value.context.rawCharacters !== undefined && <>原始上下文 {value.context.rawCharacters} 字符。</>}可整理早期回复；必须保留的内容仍有容量限制。</p></details>
    <div className="rs-conversation">{value.turns.length ? value.turns.map(turn => <TurnRecord key={turn.id} turn={turn} onTask={onTask} onQuestion={onQuestion}/>) : <div className="rs-empty"><h3>会话已创建，尚无执行轮次</h3><p>写下第一轮指令后明确开始。打开或刷新不会自动执行。</p></div>}</div>
    <SharedSources key={`${value.id}:${value.blockReason ?? ''}:${value.sharedSourceIds.join(',')}`} ownerId={ownerId} ids={value.sharedSourceIds}/>
    <SessionQuestions key={`${ownerId}:${value.id}:${value.blockReason ?? ''}`} ownerId={ownerId} sessionId={value.id} collaborationEnabled={value.collaboration?.enabled} questionId={questionId} onQuestion={onQuestion} onUse={value.allowedActions.includes('start') && !blocked && !busy ? id => { selectedReply.change(id); onQuestion(''); composer.current?.focus(); composer.current?.scrollIntoView?.({ block: 'center' }); } : undefined}/>
    <ContextStatus value={value} blocked={blocked}/>
    {(value.allowedActions.includes('start') || correction) && <form className="rw-form rs-composer" noValidate onSubmit={event => { event.preventDefault(); void send(); }}><fieldset disabled={busy || blocked}>{selectedReply.value && <div className="rs-selected-reply"><p>已选择下一轮引用：<code>{selectedReply.value}</code>。{correction ? '当前纠正不会采用这条回复。' : '提交下一轮时会重新核对回复与来源权限。'}</p><button type="button" onClick={() => selectedReply.change('')}>取消选用回复</button></div>}<label>{correction ? '补充或纠正当前研究' : '下一轮指令'}<textarea ref={composer} rows={3} maxLength={2000} value={draft.value} onChange={event => draft.change(event.target.value)} aria-invalid={!!error}/></label><p className="rw-muted">{correction ? '先保存纠正，下一次研究请求才会纳入；整理摘要不算纳入，也不会改变已经开始的调用或保证模型遵守。' : '填写的新指令只有点击开始才会发送；沿用此会话的目标和停止边界。'}</p>{error && <p role="alert" className="rw-error">{error}</p>}<button className="rw-primary">{busy ? '正在提交…' : correction ? '保存纠正' : '开始这一轮'}</button></fieldset></form>}
    {!draft.saved && <p className="rw-error" role="alert">浏览器无法保存草稿；离开前请复制当前输入。</p>}
  </section>;
}

export function ResearchSessions({ ownerId, selectedId = '', questionId = '', onSelect, onQuestion, onModels, onTask }: Props) {
  const [options, setOptions] = useState<SessionOptions | null>(null); const [page, setPage] = useState<SessionPage | null>(null);
  const [detail, setDetail] = useState<ResearchSession | null>(null); const [after, setAfter] = useState('');
  const [readError, setReadError] = useState(''); const [detailError, setDetailError] = useState(''); const [actionError, setActionError] = useState(''); const [notice, setNotice] = useState('');
  const [refresh, setRefresh] = useState(0); const [busy, setBusy] = useState(false);
  const feedback = useRef<HTMLDivElement | null>(null);
  useEffect(() => { if (actionError || notice) { feedback.current?.focus(); feedback.current?.scrollIntoView?.({ block: 'nearest' }); } }, [actionError, notice]);
  const [requests, setRequests] = useState<PendingSessionRequest[]>(() => {
    const stored = readStored<unknown>(requestKey(ownerId), []);
    return Array.isArray(stored) ? stored.filter((item): item is PendingSessionRequest => !!item && typeof item.requestId === 'string' && Object.hasOwn(actions, item.action) && (item.sessionId === null || typeof item.sessionId === 'string')) : [];
  });
  const requestRef = useRef(requests); const lock = useRef(false); const active = useRef(true); const readVersion = useRef(0); const selected = useRef(selectedId); selected.current = selectedId;
  const listRead = useRef(0);
  const detailRead = useRef<{ revision: number; value: ResearchSession | null }>({ revision: 0, value: null });
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  useEffect(() => {
    const detailRevision = detailRead.current.revision;
    const controller = new AbortController(); setReadError(''); setPage(null);
    void Promise.all([api.options(ownerId, controller.signal), api.list(ownerId, after, controller.signal)])
      .then(([nextOptions, nextPage]) => {
        if (controller.signal.aborted) return;
        listRead.current++;
        // A list reply cannot erase a detail observation made after this list
        // request began. These counters order reads, not backend task versions.
        const newer = detailRead.current.revision > detailRevision ? detailRead.current.value : null;
        setOptions(nextOptions);
        setPage(newer ? { ...nextPage, items: nextPage.items.map(item => item.id === newer.id ? { ...item, state: newer.state, updatedAt: newer.updatedAt } : item) } : nextPage);
      })
      .catch(reason => { if (!controller.signal.aborted) setReadError(describe(reason)); });
    return () => controller.abort();
  }, [ownerId, after, refresh]);
  useEffect(() => {
    setDetail(previous => previous?.id === selectedId ? previous : null); setDetailError(''); if (!selectedId) return;
    const controller = new AbortController();
    let reading = false;
    const read = async () => {
      if (reading) return; reading = true; const version = readVersion.current; const listRevision = listRead.current;
      try {
        const value = await api.get(ownerId, selectedId, controller.signal);
        if (!controller.signal.aborted && version === readVersion.current) {
          setDetail(value); setDetailError('');
          // If a list succeeded while this GET was in flight, keep that list.
          // The next detail poll can synchronize it without replaying anything.
          if (listRevision === listRead.current) {
            detailRead.current = { revision: detailRead.current.revision + 1, value };
            setPage(previous => previous ? { ...previous, items: previous.items.map(item => item.id === value.id ? { ...item, state: value.state, updatedAt: value.updatedAt } : item) } : previous);
          }
        }
      }
      catch (reason) { if (!controller.signal.aborted && version === readVersion.current) { setDetail(null); setDetailError(describe(reason)); } }
      finally { reading = false; }
    };
    void read(); const timer = window.setInterval(() => { if (document.visibilityState !== 'hidden' && !lock.current) void read(); }, 4000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [ownerId, selectedId, refresh]);
  function saveRequests(update: (previous: PendingSessionRequest[]) => PendingSessionRequest[]) {
    const latest = readStored<PendingSessionRequest[]>(requestKey(ownerId), requestRef.current);
    const next = update(Array.isArray(latest) ? latest : requestRef.current);
    if (!writeStored(requestKey(ownerId), next)) throw new Error('浏览器无法保留原请求标识，本次未发送。请允许站点存储后重试。');
    requestRef.current = next; if (active.current) setRequests(next);
  }
  async function post(action: SessionAction, sessionId: string | null, send: (requestId: string) => Promise<ResearchSession>) {
    const pointer = { requestId: crypto.randomUUID(), action, sessionId };
    saveRequests(previous => [...previous, pointer]);
    readVersion.current++;
    try {
      const result = await send(pointer.requestId);
      saveRequests(previous => previous.filter(item => item.requestId !== pointer.requestId));
      if (active.current) { if (selected.current === result.id || action === 'create') setDetail(result); setRefresh(value => value + 1); }
      return result;
    } catch (reason) {
      if (!unresolved(reason)) saveRequests(previous => previous.filter(item => item.requestId !== pointer.requestId));
      throw reason;
    }
  }
  async function run(work: () => Promise<void>): Promise<boolean> {
    if (lock.current) return false; lock.current = true; setBusy(true); setActionError(''); setNotice('');
    try { await work(); return true; }
    catch (reason) { if (active.current) setActionError(describe(reason)); return false; }
    finally { lock.current = false; if (active.current) setBusy(false); }
  }
  function create(value: Omit<CreateSession, 'requestId'>) {
    void run(async () => {
      const created = await post('create', null, requestId => api.create(ownerId, { ...value, requestId }));
      removeStored(draftKey(ownerId));
      if (!active.current) return;
      onSelect(created.id); setNotice('会话已创建，正在提交第一轮。');
      try { await post('turn', created.id, requestId => api.turn(ownerId, created.id, { requestId, text: value.goal })); }
      catch (reason) { if (active.current) setNotice('会话已创建，第一轮未确认。请先核对原请求；没有回执时不会自动重发。'); throw reason; }
      if (active.current) setNotice('第一轮请求已接收，请查看实际执行记录。');
    });
  }
  async function recover(pointer: PendingSessionRequest) {
    await run(async () => {
      const receipt = await api.request(ownerId, pointer.requestId);
      if (receipt.action !== pointer.action || pointer.sessionId && pointer.sessionId !== receipt.sessionId) throw new Error('原请求动作或会话不匹配，仍需核对。');
      saveRequests(previous => previous.filter(item => item.requestId !== pointer.requestId));
      if (active.current) { onSelect(receipt.sessionId); setDetail(receipt.session); setRefresh(value => value + 1); setNotice('已读到原请求回执。本次查询没有重新发送或启动研究。'); }
    });
  }
  const currentPending = requests.some(item => item.sessionId === selectedId || !selectedId && item.action === 'create');
  const refreshPage = useCallback(() => setRefresh(value => value + 1), []);
  return <div className="research-sessions"><div className="rs-toolbar"><button onClick={() => onSelect('')} aria-current={!selectedId ? 'page' : undefined}>新建会话</button><button disabled={busy} onClick={refreshPage}>刷新会话</button></div>
    {requests.length > 0 && <section className="rs-recovery" aria-label="待核对的会话请求"><h2>原请求仍需核对</h2><p>不会自动重发；没有查到回执也不代表未发生。</p>{requests.map(pointer => <div key={pointer.requestId}><span>{actions[pointer.action]}<code>{pointer.requestId}</code></span><button disabled={busy} onClick={() => void recover(pointer)}>查询原请求</button></div>)}</section>}
    {(actionError || notice) && <div ref={feedback} tabIndex={-1} className="rs-action-feedback">{actionError && <p className="rw-error" role="alert">{actionError}</p>}{notice && <p role="status">{notice}</p>}</div>}
    <div className="rs-layout"><aside className="rs-session-list" aria-label="我的研究会话"><h2>我的会话</h2>{readError ? <p className="rw-error" role="alert">{readError}</p> : !page ? <p role="status">正在读取会话…</p> : page.items.length ? page.items.map(item => <button key={item.id} aria-current={item.id === selectedId ? 'page' : undefined} onClick={() => onSelect(item.id)}><strong>{item.title}</strong><span>{states[item.state]} · {time(item.updatedAt)}</span></button>) : <p className="rw-muted">{after ? '本页没有会话。' : '还没有会话。提交第一个目标后，记录会保存在这里。'}</p>}<div className="rs-pagination">{after && <button onClick={() => setAfter('')}>第一页</button>}{page?.nextCursor && <button onClick={() => setAfter(page.nextCursor!)}>下一页会话</button>}</div></aside>
      <div className="rs-content">{selectedId ? detailError ? <p className="rw-error" role="alert">{detailError}</p> : detail ? <SessionDetail key={detail.id} ownerId={ownerId} value={detail} busy={busy} blocked={currentPending} questionId={questionId} onQuestion={onQuestion} onTask={onTask} onStop={() => void run(async () => { await post('stop', detail.id, requestId => api.stop(ownerId, detail.id, { requestId })); setNotice('停止请求已接收，请核对实际停止状态。'); })} onSend={(text, correction, assistantQuestionId) => run(async () => { await post(correction ? 'correct' : 'turn', detail.id, requestId => correction ? api.correct(ownerId, detail.id, { requestId, text }) : api.turn(ownerId, detail.id, { requestId, text, ...(assistantQuestionId ? { assistantQuestionId } : {}) })); setNotice(correction ? '纠正已保存；是否已纳入下一次请求请看消息状态。' : '本轮请求已接收，请查看实际执行记录。'); })}/> : <p role="status">正在读取会话详情…</p> : <CreateSessionForm ownerId={ownerId} options={options} busy={busy} blocked={currentPending} onModels={onModels} onCreate={create}/>}</div>
    </div>
  </div>;
}
