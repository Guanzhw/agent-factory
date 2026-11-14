import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { IconArrowDown, IconArrowUp, IconPlus, IconRefresh, IconSearch, IconSquare, IconFolder, IconLayoutSidebar, IconUsers, IconInfoCircle, IconX } from '@tabler/icons-react';
import { ApiError } from '../../api.js';
import { assistantApi, type ResearchSource } from './live/assistantClient.js';
import { researchSessionsApi as api, type CreateSession, type ResearchSession, type SessionAction, type SessionOptions, type SessionPage, type SessionTurn } from './researchSessionsClient.js';
import { draftKey, readStored, removeStored, requestKey, writeStored, type PendingSessionRequest, type SessionDraft } from './researchSessionStorage.js';
import { SessionQuestions } from './SessionQuestions.js';
import { SessionActivity, hasUnconfirmedOperation, isInFlightOperation } from './SessionActivity.js';
import { ResearchReply } from './ResearchReply.js';
import { CopyButton } from './CopyButton.js';
import { SessionFiles } from './SessionFiles.js';
import { ChatModelPicker } from './ChatModelPicker.js';
import './sessions.css';

type Props = { ownerId: string; selectedId?: string; questionId?: string; onSelect: (id: string) => void; onQuestion: (id: string) => void; onModels: () => void; navigation?: ReactNode; workspaceContent?: ReactNode; sessionError?: string };
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
const defaultBoundaries = '';
const initialDraft: SessionDraft = { title: '', goal: '', boundaries: '', modelConnectionRef: '' };
type ModelChoice = { modelConnectionRef: string; reasoningEffort?: string };
const memoryTools: Record<string, { operation: string; title: string; completed: string }> = {
  research_find_memories: { operation: 'find', title: '查找个人记忆', completed: '查找完成' },
  research_remember: { operation: 'remember', title: '记住个人偏好', completed: '已记住' },
  research_update_memory: { operation: 'update', title: '纠正个人记忆', completed: '已修改' },
  research_forget_memory: { operation: 'forget', title: '忘记个人记忆', completed: '已忘记' },
};
const subagentTools: Record<string, string> = { research_delegate: '分派临时子助手', research_wait_child: '等待子助手结果' };
const childStates: Record<string, string> = {
  pending: '待执行', queued: '排队中', running: '执行中', paused: '已暂停，等待继续',
  completed: '已完成', failed: '执行失败', cancelled: '已停止', canceled: '已停止', canceling: '停止请求已接收，尚未确认停止', unknown: '结果未知，请核对原子任务',
};
const turnStates: Record<string, string> = {
  reserved: '等待提交', queued: '排队中', running: '执行中', waiting_approval: '等待执行继续', finalizing: '正在核对最终结果',
  completed: '本轮已完成', failed: '本轮未完成', cancelled: '本轮已停止', canceled: '本轮已停止',
  canceling: '正在停止', unknown: '结果未知，需核对原任务',
};

function MemoryEventResult({ data }: { data: Record<string, unknown> }) {
  const tool = memoryTools[String(data.toolName)];
  const output = data.output && typeof data.output === 'object' ? data.output as Record<string, unknown> : null;
  const entry = (value: unknown): value is { id: string; text: string } => !!value && typeof value === 'object'
    && typeof (value as { id?: unknown }).id === 'string' && typeof (value as { text?: unknown }).text === 'string';
  const memories = tool.operation === 'find' ? output?.memories : output ? [output.memory] : null;
  const verified = data.outcome === 'completed' && output?.operation === tool.operation && Array.isArray(memories) && memories.every(entry)
    && (tool.operation !== 'find' || typeof output.page === 'number' && typeof output.total === 'number');
  const reason = data.code === 'RESEARCH_MEMORY_NOT_FOUND' ? '未找到你可操作的这条记忆。'
    : data.code === 'RESEARCH_MEMORY_UNAVAILABLE' ? '记忆存储暂时不可用。'
      : data.code === 'RESEARCH_TOOL_OUTPUT_TOO_LARGE' && tool.operation === 'find' ? '结果超过当前输出范围，可在下一条指令中缩小查找范围。' : '';
  if (!verified) return <div role={['failed', 'unknown'].includes(String(data.outcome)) ? 'alert' : 'status'}>
    <p>{data.outcome === 'failed' ? '本次操作未完成。' : data.outcome === 'cancelled' ? '本次工具调用已停止。' : '本次操作结果尚未确认。'} 请核对原工具记录；刷新不会重发操作。</p>
    {reason && <p>{reason}</p>}
    {typeof data.code === 'string' && <p>原因：<code>{data.code}</code></p>}
  </div>;
  return <div><p><strong>{tool.completed}</strong></p>
    {data.reconciled === true && <p>已核对原操作，未重新执行。</p>}
    {tool.operation === 'find' && <><p>{memories.length ? '以下个人记忆已返回本轮研究；是否采用请结合助手回复和后续执行记录核对。' : '本页没有匹配的个人记忆。'}</p>{typeof output.page === 'number' && typeof output.total === 'number' && <p>第 {output.page} 页 · 共 {output.total} 条匹配{typeof output.nextPage === 'number' ? ` · 还有第 ${output.nextPage} 页` : ''}</p>}</>}
    {tool.operation === 'update' && typeof output.previousText === 'string' && <><p>修改前</p><p className="rw-answer">{output.previousText}</p><p>修改后</p></>}
    {memories.map(memory => <div key={memory.id}><p className="rw-answer">{memory.text}</p><p className="rw-id">记忆条目：{memory.id}</p></div>)}
    {tool.operation === 'forget' && <p>{typeof output.notice === 'string' ? output.notice : '此条不再出现在个人记忆查询中；旧对话、摘要和已经发送的内容仍然保留。'}</p>}
  </div>;
}

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
    let disclosure = invalid.closest('details');
    while (disclosure) { disclosure.open = true; disclosure = disclosure.parentElement?.closest('details') ?? null; }
    invalid.focus({ preventScroll: true });
    invalid.closest('label')?.scrollIntoView?.({ block: 'center' });
  }, [errors]);
  useEffect(() => {
    if (!options || initialized.current) return;
    initialized.current = true;
    if (readStored(draftKey(ownerId), null) !== null) return;
    draft.change({ ...initialDraft, modelConnectionRef: options.models.find(model => model.available)?.connectionRef ?? '' });
    // Options initialize a new draft once; rereads must not overwrite an edited field.
  }, [options, ownerId]);
  useEffect(() => {
    const model = options?.models.find(item => item.available);
    if (model && !value.modelConnectionRef) draft.change({ ...value, modelConnectionRef: model.connectionRef });
  }, [options, value.modelConnectionRef]);
  function submit() {
    const problems: Record<string, string> = {};
    if (!value.goal.trim()) problems.goal = '请输入消息。';
    if (!options?.models.some(model => model.available && model.connectionRef === value.modelConnectionRef)) problems.model = '请选择当前可用的模型连接。';
    setErrors(problems);
    if (!Object.keys(problems).length) onCreate({ ...(value.projectId ? { projectId: value.projectId } : {}), modelConnectionRef: value.modelConnectionRef, ...(value.reasoningEffort ? { reasoningEffort: value.reasoningEffort } : {}), title: value.title.trim() || value.goal.trim().slice(0, 60), goal: value.goal.trim(), boundaries: value.boundaries.trim() || defaultBoundaries });
  }
  return <section className="rs-create"><div className="rs-welcome"><span>Agent Factory</span><h1>今天想一起完成什么？</h1><p>从一个问题、想法或研究目标开始。</p></div>

    <div className="rs-composer-context"><IconFolder size={16}/>{options?.workspace.configured ? '会话工作区' : '工作区尚未配置'}</div>
    <form ref={form} className="rw-form" noValidate onSubmit={event => { event.preventDefault(); submit(); }}><fieldset disabled={busy || blocked}>
      <label className="rs-prompt"><span className="sr-only">研究目标</span><textarea placeholder="向 Agent Factory 发送消息…" rows={1} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); submit(); } }} value={value.goal} onChange={event => draft.change({ ...value, goal: event.target.value })} aria-invalid={!!errors.goal}/>{errors.goal && <span role="alert">{errors.goal}</span>}</label>
      <div className="rs-compose-toolbar"><ChatModelPicker models={options?.models ?? []} modelConnectionRef={value.modelConnectionRef} reasoningEffort={value.reasoningEffort} onChange={(modelConnectionRef, reasoningEffort) => draft.change({ ...value, modelConnectionRef, reasoningEffort })} onManage={onModels}/>{errors.model && <span role="alert">{errors.model}</span>}
      {!options?.models.length && <button type="button" className="rs-text-button" onClick={onModels}>配置我的模型</button>}
<button className="rw-primary rs-send" aria-label="发送消息" disabled={!options?.available || !value.goal.trim()}>{busy ? '正在发送…' : <IconArrowUp size={20}/>}</button></div>
      <details className="rs-preferences"><summary>会话设置</summary>{options?.collaboration?.available && <p className="rs-collaboration-note">助手可按研究目标自主询问已开放的同事助手，只发送所需的问题文本。你可以随时请求停止。</p>}      <label>会话名称<input value={value.title} onChange={event => draft.change({ ...value, title: event.target.value })} aria-invalid={!!errors.title}/>{errors.title && <span role="alert">{errors.title}</span>}</label>
      <label>补充要求（可选）<textarea rows={2} placeholder="偏好、背景或希望助手遵循的要求…" value={value.boundaries} onChange={event => draft.change({ ...value, boundaries: event.target.value })} aria-invalid={!!errors.boundaries}/><small>可以留空，也可以直接写在消息中。</small>{errors.boundaries && <span role="alert">{errors.boundaries}</span>}</label>
      <details><summary>引用已有项目（可选）</summary><label>项目标识<input value={value.projectId ?? ''} onChange={event => draft.change({ ...value, projectId: event.target.value.trim() || undefined })}/></label><p>填写已确认项目的标识，助手可读取约定并按目标委派实验。留空可直接开始独立工作。</p></details>
      {options && <p className="rw-muted">{options.workspace.configured ? '文件与命令工具可供助手按需使用。' : '当前未配置本地工作目录。'}</p>}</details>


      {!options?.available && options && <p className="rw-error" role="alert">当前无法开始：{reasons[options.unavailableCode ?? ''] ?? options.unavailableCode ?? '研究环境不可用'}<small> {options.unavailableCode}</small></p>}

    </fieldset></form><p className="rs-compose-hint">Enter 发送 · Shift + Enter 换行</p>{!draft.saved && <p className="rw-error" role="alert">浏览器无法保存草稿；离开前请复制当前输入。</p>}
  </section>;
}

function toolOutput(result: Record<string, unknown> | null) {
  return result?.output && typeof result.output === 'object' && !Array.isArray(result.output) ? result.output as Record<string, unknown> : null;
}

function ToolOutput({ result }: { result: Record<string, unknown> }) {
  const output = toolOutput(result);
  if (output && Array.isArray(output.argv) && output.argv.every(item => typeof item === 'string')) return <div className="rs-command-output"><p>工作目录：{String(output.cwd ?? '')}</p>{typeof output.stdout === 'string' && output.stdout && <><h4>标准输出</h4><pre>{output.stdout}</pre></>}{typeof output.stderr === 'string' && output.stderr && <><h4>错误输出</h4><pre>{output.stderr}</pre></>}<details><summary>原工具回执</summary><pre>{JSON.stringify(result, null, 2)}</pre></details></div>;
  if (output && typeof output.path === 'string' && typeof output.afterSha256 === 'string') return <div><p><strong>{output.created === true ? '新建文件' : '修改文件'}</strong> <code>{output.path}</code></p><p>修改前：<code>{String(output.beforeSha256 ?? '文件不存在')}</code></p><p>修改后：<code>{output.afterSha256}</code></p><details><summary>原工具回执</summary><pre>{JSON.stringify(result, null, 2)}</pre></details></div>;
  return <pre>{JSON.stringify(result, null, 2)}</pre>;
}

function ToolRecord({ item, active }: { item: SessionTurn['toolResults'][number]; active: boolean }) {
  const output = toolOutput(item.result);
  const unknown = item.status.toUpperCase() === 'UNKNOWN' && !active;
  const failed = item.result?.outcome === 'failed' || typeof output?.exitCode === 'number' && output.exitCode !== 0;
  const status = unknown ? '结果未知，需核对原操作' : failed ? '操作失败' : item.result?.outcome === 'cancelled' ? '操作已停止'
    : item.status.toUpperCase() === 'DONE' ? '回执已确认' : ['RESERVED', 'UNKNOWN'].includes(item.status.toUpperCase()) ? '等待操作回执' : `回执状态：${item.status}`;
  const command = Array.isArray(output?.argv) && output.argv.every(value => typeof value === 'string') ? output.argv.join(' ') : null;
  return <details className={unknown || failed ? 'rs-tool-warning' : undefined} open={unknown || failed}>
    <summary><span role={unknown || failed ? 'alert' : undefined}>{status}{typeof output?.exitCode === 'number' && ` · 退出码 ${output.exitCode}`}</span>
      {command ? <code>{command}</code> : typeof output?.path === 'string' && <code>{output.path}</code>}</summary>
    {item.result ? <ToolOutput result={item.result}/> : <p>还没有已确认的结果。</p>}
    <p className="rw-muted">操作标识：<code>{item.effectKey}</code></p>
  </details>;
}

function TurnRecord({ turn, onQuestion }: { turn: SessionTurn; onQuestion: (id: string) => void }) {
  const replies = [...(turn.assistantReply ? [turn.assistantReply] : []), ...(turn.assistantReplies ?? [])];
  const children = turn.children ?? [];
  const legacyResults = turn.toolResults.filter(item => {
    if (isInFlightOperation(turn, item)) return false;
    const event = turn.events.findLast(event => ['research_tool_finished', 'tool_finished'].includes(event.type) && typeof event.data.callId === 'string' && item.effectKey.endsWith(':' + event.data.callId));
    return !event || !item.result || item.status.toUpperCase() !== (event.data.cancelled === true ? 'CANCELLED' : 'DONE')
      || event.data.outcome !== item.result.outcome
      || !Object.entries(item.result).every(([key, value]) => JSON.stringify(event.data[key]) === JSON.stringify(value));
  });
  return <article className="rs-turn"><header className="sr-only"><h3>第 {turn.sequence} 轮</h3><span>{turn.children?.length && turn.status === 'waiting_approval' ? (children.length ? '等待子助手结果' : '等待命令结果') : turnStates[turn.status] ?? turn.status}</span><time>{time(turn.createdAt)}</time></header>
    {turn.continuation && <div className="rs-continuation"><p>由同事回复自动发起本轮。创建轮次不代表回复已纳入模型请求，请核对下方引用与原问题状态。</p>{turn.continuation.questionIds.map(id => <button key={id} className="rs-text-button" onClick={() => onQuestion(id)}>自动继续的原问题 {id}</button>)}</div>}
    <SessionActivity turn={turn}/>
    {!!children.length && <section aria-label={`第 ${turn.sequence} 轮临时子助手`}><h4>临时子助手</h4><p className="rw-muted">本轮临时分工，使用你的工作区与授权。停止本会话也会请求停止子任务。</p>{children.map(child => <div className="rs-message rs-reply" key={child.childTaskId}>
      <p role="status">{childStates[child.status] ?? childStates.unknown}</p>
      <p className="rs-child-preview">{child.goal}</p><details className="rs-child-goal"><summary>查看委托内容</summary><p>{child.goal}</p></details>
      {child.status === 'completed' && (child.result !== null ? <details className="rs-child-result"><summary>查看子助手结果</summary><ResearchReply text={child.result}/></details> : <p className="rw-muted">尚无已确认的结果正文。</p>)}
    </div>)}</section>}
    {!!legacyResults.length && <section className="rs-tool-results" aria-label={`第 ${turn.sequence} 轮工具结果`}><h4>工具与文件记录</h4>{legacyResults.map(item => <ToolRecord key={item.effectKey} item={item} active={!hasUnconfirmedOperation(turn) && ['queued', 'running', 'waiting_approval', 'finalizing'].includes(turn.status)}/>)}</section>}
    {turn.result !== null && <div className="rs-message rs-reply"><span className="sr-only">助手回复</span><ResearchReply text={turn.result}/><div className="rs-message-actions"><CopyButton text={turn.result} label="复制助手回复"/></div></div>}
    {!!replies.length && <section className="rs-adopted-reply" aria-label={`第 ${turn.sequence} 轮引用的同事回复`}><h4>本轮引用的同事回复</h4>{replies.map(reply => <div key={reply.questionId}><button className="rs-text-button" onClick={() => onQuestion(reply.questionId)}>核对原问题 {reply.questionId}</button>{reply.state === 'available' ? <><p>{reply.questionText}</p><p>{reply.reply.text}</p><p className="rw-muted">作为引用证据，不代表实验已验证。输入依据：{reply.reply.contentIds.length ? reply.reply.contentIds.join('、') : '无可用团队依据'}</p></> : <p role="status">引用的回复当前不可用，正文与来源已隐藏；后续研究需先核对权限。</p>}</div>)}</section>}
    {turn.failure && <p className="rw-error" role="alert">本轮未完成：{turn.failure}</p>}

  </article>;
}

function TurnDiagnostics({ turn }: { turn: SessionTurn }) {
  return <details className="rs-execution"><summary>第 {turn.sequence} 轮 · {turnStates[turn.status] ?? turn.status}</summary>
    <details className="rs-events"><summary>原始事件 · {turn.events.length} 条</summary><p className="rw-muted">以下是执行端保存的诊断记录。</p>{turn.events.length ? <ol>{turn.events.map(event => <li key={event.id}><time>{time(event.createdAt)}</time><strong>{memoryTools[String(event.data.toolName)]?.title ?? subagentTools[String(event.data.toolName)] ?? event.type}</strong>{event.type === 'research_tool_finished' && Object.hasOwn(memoryTools, String(event.data.toolName)) ? <MemoryEventResult data={event.data}/> : <p>{event.message}</p>}{Object.keys(event.data).length > 0 && <details><summary>事件详情</summary><pre>{JSON.stringify(event.data, null, 2)}</pre></details>}</li>)}</ol> : <p>还没有任务事件。</p>}</details>
  </details>;
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
  return <details className="rs-sources"><summary>已引用的资料 · {ids.length}</summary><p>包括自己发布的私有资料及获准访问的共享资料。每次查看都重新核对当前权限。</p>{ids.map(id => <button key={id} disabled={busy} onClick={() => void read(id)}>{id}</button>)}{!ids.length && <p className="rw-muted">尚未引用资料。</p>}{busy && <p role="status">正在核对来源…</p>}{error && <p className="rw-error" role="alert">{error} 原来源正文已隐藏。</p>}{source && <article><h3>原资料 · {source.verificationStatus}</h3><p>作者 {source.ownerId} · 来源 {source.id}</p><pre>{JSON.stringify(source.source, null, 2)}</pre><pre>{JSON.stringify(source.content, null, 2)}</pre></article>}</details>;
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
    {summary.status === 'ready' && <p>历史摘要仅作背景；当前目标、停止边界和最新纠正单独保留，原文和操作证据仍可查看。</p>}
    {summary.status === 'failed' && <p>未能生成可用的新摘要。继续处理时保留原有有效上下文，本轮不会反复尝试整理。</p>}
    {summary.status === 'unknown' && <p>上次整理结果尚未确认，未采用新摘要。继续处理时保留原有有效上下文，本轮不会自动重发整理请求。</p>}
    <p>{summary.throughSequence > 0 ? `${summary.status === 'ready' ? '已确认的摘要覆盖至' : '上次已确认的摘要覆盖至'}第 ${summary.throughSequence} 轮。` : '尚无已确认的摘要。'} 完整研究记录仍保留在上方。</p>
    {summary.code && <p className="rs-context-code">原因代码：<code>{summary.code}</code></p>}
  </section>;
}

function SessionDetail({ ownerId, value, options, busy, blocked, questionId, onQuestion, onSend, onStop, onModels, notices, connectionStatus }: { ownerId: string; value: ResearchSession; options: SessionOptions | null; busy: boolean; blocked: boolean; questionId: string; onQuestion: (id: string) => void; onSend: (text: string, correction: boolean, model: ModelChoice, assistantQuestionId?: string) => Promise<boolean>; onStop: () => void; onModels: () => void; notices: ReactNode; connectionStatus: string }) {
  const draft = useDraft(draftKey(ownerId, value.id), ''); const [error, setError] = useState('');
  const model = useDraft<ModelChoice>(`${draftKey(ownerId, value.id)}:model`, { modelConnectionRef: value.model.connectionRef, reasoningEffort: value.model.reasoningEffort });
  const selectedReply = useDraft(`${draftKey(ownerId, value.id)}:reply`, '');
  const composer = useRef<HTMLTextAreaElement | null>(null);
  const end = useRef<HTMLDivElement | null>(null);
  const following = useRef(true); const [away, setAway] = useState(false);
  const questions = useRef<HTMLElement | null>(null);
  const [fileAttention, setFileAttention] = useState(false);
  const [questionAttention, setQuestionAttention] = useState(false);
  useEffect(() => { if (questionId) questions.current?.showPopover(); }, [questionId]);
  function openQuestion(id: string) { questions.current?.showPopover(); onQuestion(id); }
  useLayoutEffect(() => {
    const pane = end.current?.closest('.rs-content'); const content = end.current?.parentElement;
    if (!pane || !content) return;
    const distance = () => pane.scrollHeight - pane.scrollTop - pane.clientHeight;
    const scroll = () => { following.current = distance() < 180; setAway(distance() >= 180); };
    // Reading an expanded record preserves position; only real overflow offers a jump.
    const resize = new ResizeObserver(() => {
      if (following.current) pane.scrollTop = pane.scrollHeight;
      setAway(distance() >= 180);
    });
    resize.observe(content); resize.observe(pane);
    pane.addEventListener('scroll', scroll, { passive: true });
    return () => { resize.disconnect(); pane.removeEventListener('scroll', scroll); };
  }, []);
  const latest = value.turns.at(-1);
  const correction = value.state === 'running' && value.allowedActions.includes('correct');
  const stateLabel = value.state === 'idle' ? value.turns.length ? value.allowedActions.includes('start') ? '可继续' : '本轮已结束' : '待开始' : states[value.state];
  async function send() {
    if (!draft.value.trim()) { setError('请输入消息。'); return; }
    setError(''); following.current = true; if (await onSend(draft.value.trim(), correction, model.value, !correction && selectedReply.value || undefined)) { draft.change(''); if (!correction) selectedReply.change(''); }
  }
  return <section className="rs-detail" aria-label="研究会话详情"><header className="rs-detail-heading">
    <div className="rs-header-row"><h2>{value.title}</h2><div className="rs-header-actions">
      <button type="button" popoverTarget="rs-question-panel" aria-label="同事问答" title="同事问答"><IconUsers size={18}/>{questionAttention && <span className="rs-attention-dot"/>}</button>
      <button type="button" popoverTarget="rs-file-panel" aria-label="会话文件" title="会话文件"><IconFolder size={18}/>{fileAttention && <span className="rs-attention-dot"/>}</button>
      <button type="button" popoverTarget="rs-info-panel" aria-label="会话信息" title="会话信息"><IconInfoCircle size={18}/></button>
    </div></div><div className="rs-header-tabs"><span>对话</span></div>
    </header>
    <div className="rs-content"><div className="rs-detail-body" onClick={event => { if ((event.target as Element).closest('summary')) following.current = false; }}>
    {notices}
    {fileAttention && <p className="rs-panel-warning" role="alert">部分会话文件无法读取。<button type="button" popoverTarget="rs-file-panel">查看文件问题</button></p>}
    {questionAttention && <p className="rs-panel-warning" role="status">同事问答有待核对的请求或读取问题。<button type="button" popoverTarget="rs-question-panel">查看同事问答</button></p>}
    {value.state === 'stopping' && <p className="rs-warning" role="status">正在停止，等待当前操作结束…</p>}
    {value.state === 'blocked' && <p className="rw-error" role="alert">本会话不能开始新一轮：{reasons[value.blockReason ?? ''] ?? '原操作需要核对。'} 历史和原任务记录仍可查看，不会自动重放。<code>{value.blockReason}</code></p>}
    <div className="rs-conversation">{value.turns.length ? value.turns.map(turn => <TurnRecord key={turn.id} turn={turn} onQuestion={openQuestion}/>) : <div className="rs-empty"><h3>会话已创建，尚无执行轮次</h3><p>写下第一轮指令后明确开始。打开或刷新不会自动执行。</p></div>}</div>
    {!!value.sharedSourceIds.length && <SharedSources key={`${value.id}:${value.blockReason ?? ''}:${value.sharedSourceIds.join(',')}`} ownerId={ownerId} ids={value.sharedSourceIds}/>}
    {value.context.notice && <p className="rs-warning" role="status">{value.context.notice}</p>}
    <ContextStatus value={value} blocked={blocked}/>
    {(value.allowedActions.includes('start') || correction || value.state === 'running' || value.state === 'stopping') && <form className="rw-form rs-composer" noValidate onSubmit={event => { event.preventDefault(); void send(); }}>
      {away && <button type="button" className="rs-jump-latest" aria-label="回到底部" onClick={() => { following.current = true; setAway(false); end.current?.scrollIntoView({ block: 'end' }); }}><IconArrowDown size={18}/></button>}
      <fieldset>{selectedReply.value && <div className="rs-selected-reply"><p>已选择下一轮引用：<code>{selectedReply.value}</code>。{correction ? '当前纠正不会采用这条回复。' : '提交下一轮时会重新核对回复与来源权限。'}</p><button type="button" onClick={() => selectedReply.change('')}>取消选用回复</button></div>}
        {(value.allowedActions.includes('start') || correction) && <label><span className="sr-only">{correction ? '补充或纠正当前研究' : '下一轮指令'}</span><textarea ref={composer} disabled={busy || blocked} rows={1} placeholder="继续对话…" onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (draft.value.trim()) void send(); } }} value={draft.value} onChange={event => draft.change(event.target.value)} aria-invalid={!!error}/></label>}
        {error && <p role="alert" className="rw-error">{error}</p>}
        <div className="rs-compose-toolbar"><button type="button" className="rs-composer-more" popoverTarget="rs-compose-menu" aria-label="更多会话操作"><IconPlus size={20}/></button>
          <ChatModelPicker models={options?.models ?? []} modelConnectionRef={model.value.modelConnectionRef} reasoningEffort={model.value.reasoningEffort} onChange={(modelConnectionRef, reasoningEffort) => model.change({ modelConnectionRef, reasoningEffort })} onManage={onModels}/>
          {value.allowedActions.includes('stop') && (value.state === 'running' || value.state === 'stopping') && <button type="button" className="rs-stop" aria-label="请求停止" disabled={busy || value.state === 'stopping'} onClick={onStop}><IconSquare size={16}/></button>}
          {(value.allowedActions.includes('start') || correction && !!draft.value.trim()) && <button className="rw-primary rs-send" aria-label={correction ? '保存纠正' : '发送'} disabled={busy || blocked || !draft.value.trim()}>{busy ? '正在提交…' : <IconArrowUp size={20}/>}</button>}
        </div>
      </fieldset><p className="rs-compose-hint">{correction ? '发送将补充当前任务' : 'Enter 发送 · Shift + Enter 换行'}</p>
    </form>}
    {!draft.saved && <p className="rw-error" role="alert">浏览器无法保存草稿；离开前请复制当前输入。</p>}
    <div ref={end} className="rs-conversation-end"/>
    </div></div>
    <aside id="rs-info-panel" popover="auto" className="rs-detail-panel" aria-label="会话信息"><header><h3>会话信息</h3><button type="button" popoverTarget="rs-info-panel" popoverTargetAction="hide" aria-label="关闭会话信息"><IconX size={18}/></button></header><p className={`rs-state rs-state-${value.state}`} role="status">{stateLabel}</p><p>{value.model.provider} · {value.model.model}</p><p>{connectionStatus}</p><h3>起始消息</h3><p>{value.goal}</p>{value.boundaries && <><h3>补充要求</h3><p>{value.boundaries}</p></>}<p>当前上下文 {value.context.characters} 字符。</p>    {value.collaboration?.enabled ? <p className="rs-collaboration-note">{value.state === 'stopped' ? '会话已停止，之后到达的同事回复不会自动继续研究。原问题仍可核对；停止本会话不会停止同事的任务。' : '此会话可自主询问同事助手，收到回复后继续。请求停止会取消尚未采用的自动继续安排，不会停止同事的任务。'}</p> : <p className="rw-muted">此会话沿用原配置，仅支持手动向同事助手提问；自主协作仅用于具备该能力的新会话。</p>}
    {value.capabilities?.memory === false && <p className="rw-muted">此会话的原工具配置不包含个人记忆。可使用上方“新建会话”，再直接告诉助手要记住、查找、纠正或忘记的偏好。</p>}
    <section aria-label="诊断记录"><h3>诊断记录</h3>{value.turns.length ? value.turns.map(turn => <TurnDiagnostics key={turn.id} turn={turn}/>) : <p className="rw-muted">尚无执行轮次。</p>}</section>
    {value.allowedActions.includes('stop') && value.state !== 'running' && value.state !== 'stopping' && <button type="button" disabled={busy} onClick={onStop}>停止会话</button>}
</aside>
    <aside ref={questions} id="rs-question-panel" popover="auto" className="rs-detail-panel" aria-label="同事问答"><header><h3>同事问答</h3><button type="button" popoverTarget="rs-question-panel" popoverTargetAction="hide" aria-label="关闭同事问答"><IconX size={18}/></button></header><SessionQuestions key={`${ownerId}:${value.id}:${value.blockReason ?? ''}`} ownerId={ownerId} sessionId={value.id} onAttention={setQuestionAttention} collaborationEnabled={value.collaboration?.enabled} questionId={questionId} onQuestion={onQuestion} onUse={value.allowedActions.includes('start') && !blocked && !busy ? id => { selectedReply.change(id); onQuestion(''); questions.current?.hidePopover(); composer.current?.focus(); composer.current?.scrollIntoView?.({ block: 'center' }); } : undefined}/></aside>
    <aside id="rs-file-panel" popover="auto" className="rs-detail-panel" aria-label="会话文件"><header><h3>会话文件</h3><button type="button" popoverTarget="rs-file-panel" popoverTargetAction="hide" aria-label="关闭会话文件"><IconX size={18}/></button></header><SessionFiles onAttention={setFileAttention} key={value.id} ownerId={ownerId} sessionId={value.id} revision={`${latest?.id}:${latest?.status}`}/></aside>
    <div id="rs-compose-menu" popover="auto" className="rs-compose-menu"><button type="button" popoverTarget="rs-file-panel"><IconFolder size={16}/>会话文件</button><button type="button" popoverTarget="rs-question-panel"><IconUsers size={16}/>同事问答</button><button type="button" popoverTarget="rs-info-panel"><IconInfoCircle size={16}/>会话信息</button></div>
  </section>;
}

export function ResearchSessions({ ownerId, selectedId = '', questionId = '', onSelect, onQuestion, onModels, navigation, workspaceContent, sessionError }: Props) {
  const [navigationOpen, setNavigationOpen] = useState(() => !window.matchMedia('(max-width:1023px)').matches);
  useEffect(() => {
    const media = window.matchMedia('(max-width:1023px)');
    const resize = () => setNavigationOpen(!media.matches);
    media.addEventListener('change', resize);
    return () => media.removeEventListener('change', resize);
  }, []);
  const showingConversation = workspaceContent === undefined;
  const [options, setOptions] = useState<SessionOptions | null>(null); const [page, setPage] = useState<SessionPage | null>(null);
  const [detail, setDetail] = useState<ResearchSession | null>(null); const [after, setAfter] = useState('');
  const [readError, setReadError] = useState(''); const [detailError, setDetailError] = useState(''); const [actionError, setActionError] = useState(''); const [notice, setNotice] = useState('');
  const [streamError, setStreamError] = useState('');
  const [lastReceived, setLastReceived] = useState<number | null>(null);
  const [query, setQuery] = useState('');
  const [refresh, setRefresh] = useState(0); const [busy, setBusy] = useState(false);
  const feedback = useRef<HTMLDivElement | null>(null);
  useEffect(() => { if (actionError || notice) { feedback.current?.focus(); feedback.current?.scrollIntoView?.({ block: 'nearest' }); } }, [actionError, notice]);
  const [requests, setRequests] = useState<PendingSessionRequest[]>(() => {
    const stored = readStored<unknown>(requestKey(ownerId), []);
    return Array.isArray(stored) ? stored.filter((item): item is PendingSessionRequest => !!item && typeof item.requestId === 'string' && Object.hasOwn(actions, item.action) && (item.sessionId === null || typeof item.sessionId === 'string')) : [];
  });
  const requestRef = useRef(requests); const lock = useRef(false); const active = useRef(true); const readVersion = useRef(0); const selected = useRef(selectedId); selected.current = selectedId;
  const detailRead = useRef<{ revision: number; value: ResearchSession | null }>({ revision: 0, value: null });
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  useEffect(() => {
    const detailRevision = detailRead.current.revision;
    const controller = new AbortController(); setReadError(''); setPage(null);
    void Promise.all([api.options(ownerId, controller.signal), api.list(ownerId, after, controller.signal)])
      .then(([nextOptions, nextPage]) => {
        if (controller.signal.aborted) return;
        // A list reply cannot erase a detail observation made after this list
        // request began. This revision orders reads, not backend task versions.
        const newer = detailRead.current.revision > detailRevision ? detailRead.current.value : null;
        setOptions(nextOptions);
        setPage(newer ? { ...nextPage, items: nextPage.items.map(item => item.id === newer.id ? { ...item, state: newer.state, updatedAt: newer.updatedAt } : item) } : nextPage);
      })
      .catch(reason => { if (!controller.signal.aborted) setReadError(describe(reason)); });
    return () => controller.abort();
  }, [ownerId, after, refresh, showingConversation]);
  useEffect(() => {
    setDetail(previous => previous?.id === selectedId ? previous : null); setDetailError(''); setLastReceived(null); if (!selectedId) return;
    const controller = new AbortController();
    let reconnect: ReturnType<typeof setTimeout> | undefined;
    async function watch() {
      const version = readVersion.current;
      try {
        await api.watch(ownerId, selectedId, controller.signal, value => {
          if (controller.signal.aborted || version !== readVersion.current) return;
          setDetail(value); setDetailError(''); setStreamError(''); setLastReceived(Date.now());
          detailRead.current = { revision: detailRead.current.revision + 1, value };
          setPage(previous => previous ? { ...previous, items: previous.items.map(item => item.id === value.id ? { ...item, state: value.state, updatedAt: value.updatedAt } : item) } : previous);
        });
      } catch (reason) {
        if (!controller.signal.aborted && version === readVersion.current) {
          if (reason instanceof ApiError && [403, 404].includes(reason.status)) {
            setDetail(null); setDetailError(describe(reason)); return;
          }
          setStreamError(reason instanceof TypeError ? '实时连接暂时中断，正在重连。' : describe(reason)); reconnect = setTimeout(() => void watch(), 1500);
        }
      }
    }
    setStreamError('');
    void watch();
    return () => { controller.abort(); clearTimeout(reconnect); };

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
      if (active.current) { if (selected.current === result.id || action === 'create') setDetail(result); }
      return result;
    } catch (reason) {
      if (!unresolved(reason)) saveRequests(previous => previous.filter(item => item.requestId !== pointer.requestId));
      throw reason;
    } finally {
      // A lost POST acknowledgement must not leave the subscription pinned to
      // the pre-command read version. Reopen it and only read persisted state.
      if (active.current) setRefresh(value => value + 1);
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
      catch (reason) { if (active.current) setNotice('会话已保存，消息发送结果暂未确认。'); throw reason; }
      if (active.current) setNotice('');
    });
  }
  async function recover(pointer: PendingSessionRequest) {
    await run(async () => {
      const receipt = await api.request(ownerId, pointer.requestId);
      if (receipt.action !== pointer.action || pointer.sessionId && pointer.sessionId !== receipt.sessionId) throw new Error('原请求动作或会话不匹配，仍需核对。');
      saveRequests(previous => previous.filter(item => item.requestId !== pointer.requestId));
      if (active.current) { onSelect(receipt.sessionId); setDetail(receipt.session); setRefresh(value => value + 1); setNotice('操作结果已更新。'); }
    });
  }
  const currentPending = requests.some(item => item.sessionId === selectedId || !selectedId && item.action === 'create');
  const refreshPage = useCallback(() => setRefresh(value => value + 1), []);
  const connectionStatus = streamError ? `${streamError} 当前活动与结果尚未确认。` : lastReceived ? `已接收会话快照 · ${new Date(lastReceived).toLocaleTimeString('zh-CN')}` : '正在连接实时事件…';
  const notices = <>{sessionError && <p role="alert" className="rw-error">{sessionError}</p>}{showingConversation && selectedId && <p className={`rs-connection${streamError ? ' rs-stream-status' : ' sr-only'}`} role="status">{connectionStatus}</p>}    {!busy && requests.length > 0 && <section className="rs-recovery" aria-label="操作结果未确认"><p role="status">未能确认操作结果。</p>{requests.map(pointer => <div key={pointer.requestId}><span>{actions[pointer.action]}</span><button onClick={() => void recover(pointer)}>重新获取</button></div>)}</section>}
    {(actionError || notice) && <div ref={feedback} tabIndex={-1} className="rs-action-feedback">{actionError && requests.length === 0 && <p className="rw-error" role="alert">{actionError}</p>}{notice && <p role="status">{notice}</p>}</div>}
</>;
  return <div className="research-sessions">    <div className="rs-layout"><aside className="rs-session-list" aria-label="我的研究会话"><details className="rs-navigation" open={navigationOpen} onToggle={event => setNavigationOpen(event.currentTarget.open)}><summary aria-label={navigationOpen ? '收起侧边栏' : '展开侧边栏'}><IconLayoutSidebar size={18}/><span>会话与导航</span></summary><div className="rs-navigation-body">{navigation}<div className="rs-toolbar"><button onClick={() => onSelect('')} aria-current={!selectedId ? 'page' : undefined}><IconPlus size={16}/>新建会话</button><button aria-label="刷新会话" title="刷新会话" disabled={busy} onClick={refreshPage}><IconRefresh size={16}/></button></div><label className="rs-session-search"><IconSearch size={15}/><input aria-label="搜索本页会话" placeholder="搜索会话" value={query} onChange={event => setQuery(event.target.value)}/></label><h2>工作区</h2>{readError ? <p className="rw-error" role="alert">{readError}</p> : !page ? <p role="status">正在读取会话…</p> : page.items.length ? page.items.filter(item => item.title.toLocaleLowerCase().includes(query.toLocaleLowerCase())).map(item => <button key={item.id} aria-current={item.id === selectedId ? 'page' : undefined} onClick={() => { onSelect(item.id); if (window.matchMedia('(max-width:767px)').matches) setNavigationOpen(false); }}><strong>{item.title}</strong><span>{states[item.state]} · {time(item.updatedAt)}</span></button>) : <p className="rw-muted">{after ? '本页没有会话。' : '还没有会话。提交第一个目标后，记录会保存在这里。'}</p>}<div className="rs-pagination">{after && <button onClick={() => setAfter('')}>第一页</button>}{page?.nextCursor && <button onClick={() => setAfter(page.nextCursor!)}>下一页会话</button>}</div></div></details></aside>
      <main className={detail && showingConversation ? 'rs-main' : `rs-content${workspaceContent !== undefined ? ' rs-settings-content' : ''}`}>{!(detail && showingConversation) && notices}
{workspaceContent !== undefined ? workspaceContent : selectedId ? detailError ? <p className="rw-error" role="alert">{detailError}</p> : detail ? <SessionDetail options={options} onModels={onModels} notices={notices} connectionStatus={connectionStatus} key={detail.id} ownerId={ownerId} value={detail} busy={busy} blocked={currentPending} questionId={questionId} onQuestion={onQuestion} onStop={() => void run(async () => { await post('stop', detail.id, requestId => api.stop(ownerId, detail.id, { requestId })); })} onSend={(text, correction, model, assistantQuestionId) => run(async () => { await post(correction ? 'correct' : 'turn', detail.id, requestId => correction ? api.correct(ownerId, detail.id, { requestId, text }) : api.turn(ownerId, detail.id, { requestId, text, modelConnectionRef: model.modelConnectionRef, reasoningEffort: model.reasoningEffort ?? null, ...(assistantQuestionId ? { assistantQuestionId } : {}) })); setNotice(correction ? '补充消息已保存。' : ''); })}/> : <p role="status">正在读取会话详情…</p> : <CreateSessionForm ownerId={ownerId} options={options} busy={busy} blocked={currentPending} onModels={onModels} onCreate={create}/>}</main>
    </div>
  </div>;
}
