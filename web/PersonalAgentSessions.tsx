import './personalAgentSessions.css';
import { PersonalSessionRebind } from './PersonalSessionRebind.js';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api.js';
import { PlanReviewGate } from './PlanReviews.js';
import { personalRemoteApi, definitivelyRejected } from './personalRemoteApi.js';
import { PERSONAL_CONTRACT, PERSONAL_PROVIDER, ORX_PERSONAL_PROVIDER, personalAgentApi, checkPersonalRecovery, checkAttachment, type PersonalAttachment, type NativePersonalSession, type PersonalNamespace, type PersonalAction, type PersonalIntent, type PersonalProject, type PersonalSession } from './personalAgentApi.js';
import type { FactoryJob, Plan, UserConnection } from './models.js';

type Props = { ownerId: string; onTask?: (id: string) => void; connectionRef?: string; namespace?: PersonalNamespace };
type Pending = { requestId: string; planId?: string; startPlanId?: string };
const labels = { create: '创建 OpenCode 会话', prompt: '发送下一轮消息', interrupt: '请求尽力中断' };
const warning = '模型凭据保留在远程服务，模型费用由你与远程服务商结算。Factory 不保证远程硬预算；中断仅尽力而为，停止状态未经证实。';
export function PersonalAgentSessions(props: Props) { return <PersonalSessions key={`${props.ownerId}:${props.namespace ?? 'opencode'}`} {...props} />; }
function PersonalSessions({ ownerId, onTask, connectionRef, namespace = 'opencode' }: Props) {
  const engine = namespace === 'opencode' ? 'OpenCode' : 'OpenResearch';
  const provider = namespace === 'opencode' ? PERSONAL_PROVIDER : ORX_PERSONAL_PROVIDER;
  const storage = `factory-personal-command:${encodeURIComponent(ownerId)}${namespace === 'opencode' ? '' : ':native-openresearch'}`;
  const attachStorage = `factory-personal-attach:${encodeURIComponent(ownerId)}:${namespace}`;
  const [attachment, setAttachment] = useState<PersonalAttachment | null>(() => { try { const value = JSON.parse(localStorage.getItem(attachStorage) ?? 'null'); return value && ['requestId', 'connectionRef', 'nativeProjectId', 'nativeSessionId'].every(key => typeof value[key] === 'string' && /^[a-zA-Z0-9_.:-]{1,200}$/.test(value[key])) ? { requestId: value.requestId, connectionRef: value.connectionRef, nativeProjectId: value.nativeProjectId, nativeSessionId: value.nativeSessionId } : null; } catch { return null; } });
  const [nativeSessions, setNativeSessions] = useState<NativePersonalSession[]>([]);
  const [pending, setPending] = useState<Pending | null>(() => { try { const p = JSON.parse(localStorage.getItem(storage) ?? 'null'); return p && /^[a-zA-Z0-9_.:-]{8,100}$/.test(p.requestId) && (!p.planId || /^[a-zA-Z0-9_.:-]{1,100}$/.test(p.planId)) ? { requestId: p.requestId, ...(p.planId ? { planId: p.planId } : {}), ...(p.startPlanId && p.startPlanId === p.planId ? { startPlanId: p.startPlanId } : {}) } : null; } catch { return null; } });
  const rebindActive = useRef(false); const observationGeneration = useRef(0);
  const [sessionCatalog, setSessionCatalog] = useState<PersonalSession[]>([]); const [rebindPending, setRebindPending] = useState(false);
  const rebindChanged = useCallback((value: boolean) => { rebindActive.current = value; setRebindPending(value); }, []);
  const [connections, setConnections] = useState<UserConnection[]>([]); const [selected, setSelected] = useState(connectionRef ?? '');
  const [project, setProject] = useState<PersonalProject>(); const [sessions, setSessions] = useState<PersonalSession[]>([]); const [session, setSession] = useState<PersonalSession>();
  const [ready, setReady] = useState(false); const [resourceReady, setResourceReady] = useState(false); const [busy, setBusy] = useState(''); const [notice, setNotice] = useState('');
  const [title, setTitle] = useState(''); const [text, setText] = useState(''); const [plan, setPlan] = useState<Plan>(); const [action, setAction] = useState<PersonalAction>();
  const [consent, setConsent] = useState(false); const [allowed, setAllowed] = useState(false); const [showReview, setShowReview] = useState(false); const [job, setJob] = useState<FactoryJob>(); const [revision, refresh] = useState(0);
  const dialog = useRef<HTMLDialogElement>(null);
  const live = useRef(true); const lock = useRef(false); const navigation = useRef(0);
  useEffect(() => { live.current = true; return () => { live.current = false; navigation.current++; }; }, []);
  useEffect(() => {
    const element = dialog.current; if (!showReview || !element) return;
    element.showModal(); return () => { element.close(); };
  }, [showReview, plan?.id]);
  const current = (epoch: number) => live.current && navigation.current === epoch;
  function remember(p: Pending | null) { if (p) localStorage.setItem(storage, JSON.stringify(p)); else localStorage.removeItem(storage); setPending(p); }
  useEffect(() => {
    const ctrl = new AbortController(); setReady(false);
    void Promise.all([api.session(ctrl.signal), personalAgentApi.capabilities(ctrl.signal), api.userConnections(ctrl.signal), personalRemoteApi.list(ctrl.signal), personalAgentApi.sessions(undefined, ctrl.signal)]).then(([who, cap, refs, remotes, history]) => {
      if (ctrl.signal.aborted) return;
      if (who.id !== ownerId || cap.executionContract !== PERSONAL_CONTRACT || cap.nativeQueue !== true || refs.some(r => r.ownerId !== ownerId)) throw new Error('identity');
      setSessionCatalog(history.filter(item => item.namespace === namespace));
      const personal = new Set(remotes.filter(r => r.providerId === provider).map(r => r.registrationRef));
      setConnections(refs.filter(r => personal.has(r.registrationRef) && r.kind === (namespace === 'opencode' ? 'environment' : 'orx') && r.status === 'active' && r.available && r.taskId === null && r.capabilities.includes('session:read'))); setReady(true);
    }).catch(() => { if (!ctrl.signal.aborted) { setConnections([]); setNotice('个人会话功能尚未启用或身份无法核对。旧只读连接不会自动升级。'); } });
    return () => ctrl.abort();
  }, [ownerId, namespace, provider, revision]);
  useEffect(() => {
    const ctrl = new AbortController(); setResourceReady(false); setProject(undefined); setSessions([]); setSession(current => current?.connectionRef === selected ? current : undefined); setNativeSessions([]);
    if (ready && connections.some(c => c.ref === selected)) {
      void Promise.all([personalAgentApi.project(selected, ctrl.signal), personalAgentApi.sessions(selected, ctrl.signal)]).then(([p, s]) => {
        if (!ctrl.signal.aborted) { if (p.namespace !== namespace || s.some(item => item.namespace !== namespace || item.connectionRef !== selected || item.nativeProjectId !== p.nativeProjectId)) throw new Error('scope'); setProject(p); setSessions(s); setResourceReady(true); }
      }).catch(() => { if (!ctrl.signal.aborted) setNotice('无法核对原生项目与会话。请刷新资源状态。'); });
    }
    return () => ctrl.abort();
  }, [ready, connections, selected, namespace]);
  const sessionId = session?.id;
  useEffect(() => {
    if (!sessionId) return;
    const generation = observationGeneration.current; const ctrl = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const result = await personalAgentApi.session(sessionId!, ctrl.signal); if (!ctrl.signal.aborted && generation === observationGeneration.current) { if (result.namespace !== namespace) throw new Error('namespace'); setSession(result); } }
      catch { if (!ctrl.signal.aborted && generation === observationGeneration.current) { setSession(current => current && current.id === sessionId ? { ...current, bindingStatus: 'unavailable' } : current); setNotice('远程观察暂不可用。保留原会话与请求；不能据此认定已停止。'); } }
      if (!ctrl.signal.aborted) timer = setTimeout(() => void poll(), 4000);
    }
    void poll(); return () => { ctrl.abort(); clearTimeout(timer); };
  }, [sessionId, namespace, session?.connectionPin?.fingerprint]);
  async function act(name: string, work: () => Promise<void>) {
    if (lock.current) return; lock.current = true; setBusy(name); const epoch = navigation.current;
    try { await work(); } catch { if (current(epoch)) setNotice('结果尚未确认。请核对原请求，不会自动提交新的请求或重放远程命令。'); }
    finally { lock.current = false; if (current(epoch)) setBusy(''); }
  }
  async function prepare(next: PersonalAction) {
    if (next !== 'create' && (!sessionWritable || !session?.connectionPin?.capabilities.includes(`session:${next}`))) return;
    if (!ready || !resourceReady || pending || attachment || rebindPending || rebindActive.current || lock.current || !project || next !== 'create' && !session?.nativeSessionId || next === 'prompt' && (!text.trim() || session?.activeRequestId)) return;
    const epoch = navigation.current;
    await act('prepare', async () => {
      const who = await api.session(); if (!current(epoch) || who.id !== ownerId) return;
      const requestId = crypto.randomUUID(); remember({ requestId });
      const intent: PersonalIntent = next === 'create' ? { requestId, action: next, connectionRef: selected, nativeProjectId: project.nativeProjectId, title: title.trim() || 'Factory personal session' } : next === 'prompt' ? { requestId, action: next, sessionId: session!.id, text } : { requestId, action: next, sessionId: session!.id };
      let result;
      try { result = await personalAgentApi.prepare(intent); } catch (error) { if (current(epoch) && error instanceof ApiError && definitivelyRejected(error.status)) { remember(null); setNotice('方案请求已明确拒绝，未启动远程命令。请检查权限与配置。'); return; } throw error; }
      if (!current(epoch)) return;
      remember({ requestId, planId: result.plan.id }); setPlan(result.plan); setAction(next); setConsent(false); setAllowed(false); setShowReview(true); setText(''); setNotice('固定命令方案已准备，尚未启动远程命令。');
    });
  }
  async function start() {
    if (rebindActive.current || !plan || !pending || pending.startPlanId || !consent || !allowed || lock.current) return;
    const epoch = navigation.current;
    await act('start', async () => {
      const who = await api.session(); if (!current(epoch) || who.id !== ownerId) return;
      remember({ ...pending, startPlanId: plan.id }); setAllowed(false);
      const result = await personalAgentApi.start(plan.id); if (!current(epoch)) return;
      if (result.ownerId !== ownerId) throw new Error('owner');
      setJob(result); setShowReview(false); setNotice('Factory 命令任务已接收。任务完成只表示远程命令受理或观察完成，不证明远程已停止。请核对原请求。');
    });
  }
  async function recover() {
    if (!pending || lock.current) return; const epoch = navigation.current;
    await act('recover', async () => {
      const who = await api.session(); if (!current(epoch) || who.id !== ownerId) return;
      const result = checkPersonalRecovery(await personalAgentApi.recover(pending.requestId), pending.requestId, pending.planId, pending.startPlanId); if (!current(epoch)) return;
      if (pending.planId && result.plan.id !== pending.planId || result.job && result.job.ownerId !== ownerId || result.receipt && result.receipt.session.namespace !== namespace) throw new Error('scope');
      setPlan(result.plan); setJob(result.job ?? undefined); setConsent(false); setAllowed(false);
      if (!result.job) {
        if (pending.startPlanId) { setShowReview(false); setNotice('原启动结果仍未知；尚未找到任务不代表没有启动。请保留原请求继续核对，不重放命令。'); }
        else { remember({ requestId: pending.requestId, planId: result.plan.id }); setShowReview(true); setNotice('原方案已找到；没有自动启动。请重新审阅并单独确认。'); }
      }
      else {
        remember({ requestId: pending.requestId, planId: result.plan.id, startPlanId: result.plan.id }); setShowReview(false);
        if (result.receipt) {
          setSession(result.receipt.session);
          if (result.receipt.state !== 'ack_unknown') { remember(null); setPlan(undefined); setNotice('原命令回执已核对。远程停止仍未经证实；下一轮须等待原回复观察完成。'); }
          else setNotice('原远程命令确认未知。保留原请求，不自动重放；请在远程服务核对。');
        } else setNotice('已找到原 Factory 命令任务，远程回执尚未就绪。请稍后继续核对原请求。');
      }
    });
  }
  async function readNative() {
    if (disabled || !project) return; const epoch = navigation.current;
    await act('read-native', async () => {
      const result = await personalAgentApi.nativeSessions(selected); if (!current(epoch)) return;
      if (result.namespace !== namespace || result.nativeProjectId !== project.nativeProjectId) throw new Error('scope');
      setNativeSessions(result.sessions);
    });
  }
  async function attachNative(native: NativePersonalSession) {
    if (rebindActive.current || disabled || !project || native.nativeProjectId !== project.nativeProjectId) return; const epoch = navigation.current;
    await act('attach', async () => {
      const who = await api.session(); if (!current(epoch) || who.id !== ownerId) return;
      const input = { requestId: crypto.randomUUID(), connectionRef: selected, nativeProjectId: project.nativeProjectId, nativeSessionId: native.nativeSessionId };
      localStorage.setItem(attachStorage, JSON.stringify(input)); setAttachment(input);
      let result;
      try { result = checkAttachment(await personalAgentApi.attach(input), input, namespace); }
      catch (error) { if (current(epoch) && error instanceof ApiError && definitivelyRejected(error.status)) { localStorage.removeItem(attachStorage); setAttachment(null); setNotice('原生会话关联已明确拒绝，未发送消息或创建远程会话。'); return; } throw error; }
      if (!current(epoch)) return;
      localStorage.removeItem(attachStorage); setAttachment(null); setSession(result.session); setSessions(all => [...all.filter(item => item.id !== result.session.id), result.session]); setNotice('原生会话已只读关联。继续消息或中断仍需单独制定方案、审阅并确认。');
    });
  }
  async function recoverAttach() {
    if (!attachment || lock.current) return; const epoch = navigation.current;
    await act('recover-attach', async () => {
      const who = await api.session(); if (!current(epoch) || who.id !== ownerId) return;
      const result = checkAttachment(await personalAgentApi.recoverAttachment(attachment.requestId), attachment, namespace);
      if (!current(epoch)) return;
      localStorage.removeItem(attachStorage); setAttachment(null); setSession(result.session); setSessions(all => [...all.filter(item => item.id !== result.session.id), result.session]); setNotice('已核对原只读关联请求；未重放关联或发送消息。');
    });
  }
  function closeReview() { navigation.current++; setShowReview(false); setConsent(false); setAllowed(false); setBusy(''); setNotice('已关闭审阅，未因此启动命令。原请求保留，可继续核对。'); }
  const disabled = !!busy || !!pending || !!attachment || rebindPending || !resourceReady;
  const sessionWritable = session && connections.some(item => item.ref === session.connectionRef && !!session.connectionPin && item.fingerprint === session.connectionPin.fingerprint) && (!session.bindingStatus || session.bindingStatus === 'active');
  const visibleSessions = [...new Map([...sessionCatalog, ...sessions].map(item => [item.id, item])).values()];
  const canCreate = connections.find(c => c.ref === selected)?.capabilities.includes('session:create') === true && (namespace === 'opencode' || project?.sessionCreationSupported === true);
  return <section aria-label={`个人 ${engine} 会话`}><h2>个人远程会话</h2><p>普通模式：连接已有 {engine} 服务，使用它原有的项目与会话。模型密钥留在远程端，无需在 Factory 输入。</p>
    <p className="policy-note">{warning}</p><p>{namespace === 'opencode' ? '这是 OpenCode 原生会话，不是 upstream ORX 项目。' : '这是已有 OpenResearch 项目与原生会话；不是受管单轮文本探测。'}不代表完整科研流程验收或真实端到端兼容性验证。</p>
    {notice && <p role="status">{notice}</p>}
    <label>个人会话资源<select aria-label="个人会话资源" disabled={!ready || !!busy || !!pending || !!attachment || rebindPending} value={selected} onChange={e => { navigation.current++; setSelected(e.target.value); setPlan(undefined); setText(''); }}><option value="">选择已明确绑定的个人资源</option>{connections.map(c => <option key={c.ref} value={c.ref}>{c.ref}</option>)}</select></label>
    {ready && !connections.length && <p>请以 {provider} 单独配置、验证并绑定个人资源。旧只读绑定不会获得执行能力。</p>}
    {project && <><p>{engine} 原生项目 ID：{project.nativeProjectId}</p>{canCreate && <><label>新会话标题<input aria-label="新会话标题" maxLength={120} value={title} disabled={disabled} onChange={e => setTitle(e.target.value)} /></label><button disabled={disabled} onClick={() => void prepare('create')}>准备创建会话</button></>}</>}
    {project && <section aria-label="已有原生会话"><h3>关联已有 {engine} 会话</h3><p>只读取现有会话并保存本地关联，不创建远程会话或调用模型。{!canCreate && '此提供方当前仅支持已有会话；新会话创建未启用。'}</p><button disabled={disabled} onClick={() => void readNative()}>读取已有原生会话</button>{nativeSessions.map(native => <p key={native.nativeSessionId}>{native.title ?? native.nativeSessionId} · 原生 ID {native.nativeSessionId}<button disabled={disabled} onClick={() => void attachNative(native)}>关联原生会话 {native.nativeSessionId}</button></p>)}</section>}
    <div>{visibleSessions.map(s => <button key={s.id} disabled={!!busy || !!pending || !!attachment || rebindPending} onClick={() => { navigation.current++; setSession(s); setSelected(s.connectionRef); setText(''); }}>打开 {engine} 会话 {s.nativeSessionId ?? '创建确认未知'}</button>)}</div>
    {session && <article aria-label="原生会话详情"><h3>{engine} 原生会话 ID：{session.nativeSessionId ?? '确认未知'}</h3><p>项目 {session.nativeProjectId} · 状态 {session.state} · 停止未经证实</p>
      {!sessionWritable && <p role="alert">原绑定已到期、撤销或变更，或当前无法核对。保留原结果；请重新验证资源并在下方明确续接同一原生会话。禁止用新会话代替原请求。</p>}
      {session.observation?.correlationSource && <p>回复关联：{session.observation.correlationSource}。精确轮次未验证；不能据此确认科学结论或远程已停止。</p>}
      {session.activeRequestId && <p>原消息仍待核对：{session.activeRequestId}。等待原回复完成后才能继续发送。</p>}
      {session.observation?.messages.map(m => <article key={m.id}>{m.correlationSource && <p>关联来源：{m.correlationSource}，仅为远程观察，不能作为精确轮次或科学结论证明。</p>}<h4>{m.role === 'assistant' ? '远程代理' : '你'} · {m.completed ? '远程报告回复完成' : '未报告完成'}</h4>{m.events.map((event, i) => event.type === 'text' ? <p key={i} style={{ whiteSpace: 'pre-wrap' }}>{event.text}</p> : <details key={i}><summary>工具 {event.tool} · {event.status}</summary><pre>{event.output}</pre></details>)}{m.role === 'assistant' && <p>远程报告用量（未验证，仅供参考，不是共享账本发票）：{m.usageProvenance !== 'unavailable' && m.usage ? JSON.stringify(m.usage) : '未提供'}</p>}</article>)}
      <label>下一轮消息<textarea aria-label="下一轮消息" value={text} maxLength={16000} disabled={disabled || !sessionWritable || !session.connectionPin?.capabilities.includes('session:prompt') || !!session.activeRequestId || !session.nativeSessionId} onChange={e => setText(e.target.value)} /></label><button disabled={disabled || !sessionWritable || !session.connectionPin?.capabilities.includes('session:prompt') || !!session.activeRequestId || !session.nativeSessionId || !text.trim()} onClick={() => void prepare('prompt')}>准备发送消息</button><button disabled={disabled || !sessionWritable || !session.connectionPin?.capabilities.includes('session:interrupt') || !session.nativeSessionId} onClick={() => void prepare('interrupt')}>准备尽力中断</button>
    </article>}
    <PersonalSessionRebind ownerId={ownerId} namespace={namespace} session={session} candidates={connections} disabled={!!busy || !!attachment || !ready} commandPending={!!pending} onPending={rebindChanged} onRebound={next => { navigation.current++; observationGeneration.current++; setSession(next); setSelected(next.connectionRef); setSessions(all => [...all.filter(item => item.id !== next.id), next]); setSessionCatalog(all => [...all.filter(item => item.id !== next.id), next]); setText(''); setPlan(undefined); setShowReview(false); refresh(n => n + 1); }} />
    {attachment && <p role="alert">原只读关联请求：{attachment.requestId}<button disabled={!!busy} onClick={() => void recoverAttach()}>核对原会话关联</button></p>}
    {pending && <p role="alert">原请求：{pending.requestId}<button disabled={!!busy} onClick={() => void recover()}>核对原会话命令</button></p>}
    {job && <p>Factory 命令任务：{job.id} · {job.status}。本地成功不证明远程已停止。{onTask && <button onClick={() => onTask(job.id)}>查看命令任务</button>}</p>}
    <button disabled={!!busy} onClick={() => { navigation.current++; setShowReview(false); setConsent(false); setAllowed(false); refresh(n => n + 1); }}>刷新个人资源</button>
    {showReview && plan && <dialog ref={dialog} className="personal-session-dialog" role="dialog" aria-modal="true" aria-label="审阅个人会话命令" onCancel={event => { event.preventDefault(); closeReview(); }}><h3>{action === 'create' ? `创建 ${engine} 会话` : action ? labels[action] : '原个人会话命令'}：固定方案</h3><p>{warning}</p><p>方案 {plan.id} · {plan.status === 'ready' ? '就绪' : '阻塞'}</p><pre>{JSON.stringify(plan.inputValues ?? {}, null, 2)}</pre>{plan.missing?.length > 0 && <p>{plan.missing.join('、')}</p>}
      <PlanReviewGate ownerId={ownerId} plan={plan} busy={busy} act={act} onAllowed={setAllowed} />
      <label><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} disabled={!!busy || !!pending?.startPlanId} />我确认此命令可能使用远程付费模型，接受远程自付费用、建议性预算和停止未经证实的限制</label>
      <button disabled={!!busy || !consent || !allowed || plan.status !== 'ready' || !!pending?.startPlanId} onClick={() => void start()}>确认启动此命令任务</button><button onClick={closeReview}>关闭审阅</button>
    </dialog>}
  </section>;
}
