import './personalAgentSessions.css';
import { PersonalSessionRebind } from './PersonalSessionRebind.js';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useFeeManagement } from './FeeVisibility.js';
import { api, ApiError } from './api.js';
import { PlanReviewGate } from './PlanReviews.js';
import { personalRemoteApi, definitivelyRejected } from './personalRemoteApi.js';
import { PERSONAL_CONTRACT, PERSONAL_PROVIDER, ORX_PERSONAL_PROVIDER, personalAgentApi, checkPersonalRecovery, checkAttachment, type PersonalAttachment, type NativePersonalSession, type PersonalNamespace, type PersonalAction, type PersonalIntent, type PersonalProject, type PersonalSession } from './personalAgentApi.js';
import { statusNames, type FactoryJob, type Plan, type UserConnection } from './models.js';

type Props = { onResources?: () => void; ownerId: string; onTask?: (id: string) => void; connectionRef?: string; namespace?: PersonalNamespace };
type Pending = { requestId: string; planId?: string; startPlanId?: string; submitAttempt?: true };
const labels = { create: '创建 OpenCode 会话', prompt: '发送下一轮消息', interrupt: '请求尽力中断' };
const warning = '会话使用远程服务的模型配置。中断仅尽力而为，停止状态以服务端记录为准。';
const sessionStates: Record<string, string> = { ready: '可准备消息', result_observed: '已观察到远程回复', ack_unknown: '命令回执未确认', pending: '等待回执', creating: '等待创建确认' };
function CommandSummary({ plan }: { plan: Plan }) {
  const values = plan.inputValues ?? {};
  const text = (key: string) => typeof values[key] === 'string' && values[key] ? values[key] as string : '未提供';
  const action = text('action');
  return <section className="personal-command-summary" aria-label="此次固定命令范围"><h4>此次固定命令范围</h4><dl className="plan-details"><dt>动作</dt><dd>{({ create: '创建原生会话', prompt: '发送下一轮消息', interrupt: '请求尽力中断' } as Record<string, string>)[action] ?? '动作未确认，请核对技术快照'}</dd><dt>原生项目 ID</dt><dd>{text('nativeProjectId')}</dd>{action === 'create' ? <><dt>新会话标题</dt><dd>{text('title')}</dd></> : <><dt>原生会话 ID</dt><dd>{text('nativeSessionId')}</dd></>}</dl>{action === 'prompt' && <><h4>将发送的消息</h4><p className="personal-command-text">{text('text')}</p></>}{action === 'interrupt' && <p>仅向原会话请求中断，不证明工具、模型或远端进程已停止。</p>}<details className="technical-detail"><summary>固定方案与连接技术快照</summary><span>方案 {plan.id}</span><pre>{JSON.stringify(values, null, 2)}</pre></details></section>;
}
export function PersonalAgentSessions(props: Props) { return <PersonalSessions key={`${props.ownerId}:${props.namespace ?? 'opencode'}`} {...props} />; }
function PersonalSessions({ ownerId, onTask, onResources, connectionRef, namespace = 'opencode' }: Props) {
  const feeManagementEnabled = useFeeManagement();
  const engine = namespace === 'opencode' ? 'OpenCode' : 'OpenResearch';
  const provider = namespace === 'opencode' ? PERSONAL_PROVIDER : ORX_PERSONAL_PROVIDER;
  const storage = `factory-personal-command:${encodeURIComponent(ownerId)}${namespace === 'opencode' ? '' : ':native-openresearch'}`;
  const selectionStorage = `factory-personal-session:${encodeURIComponent(ownerId)}:${namespace}`;
  const attachStorage = `factory-personal-attach:${encodeURIComponent(ownerId)}:${namespace}`;
  const [attachment, setAttachment] = useState<PersonalAttachment | null>(() => { try { const value = JSON.parse(localStorage.getItem(attachStorage) ?? 'null'); return value && ['requestId', 'connectionRef', 'nativeProjectId', 'nativeSessionId'].every(key => typeof value[key] === 'string' && /^[a-zA-Z0-9_.:-]{1,200}$/.test(value[key])) ? { requestId: value.requestId, connectionRef: value.connectionRef, nativeProjectId: value.nativeProjectId, nativeSessionId: value.nativeSessionId } : null; } catch { return null; } });
  const [nativeSessions, setNativeSessions] = useState<NativePersonalSession[]>([]);
  const [pending, setPending] = useState<Pending | null>(() => { try { const p = JSON.parse(localStorage.getItem(storage) ?? 'null'); return p && /^[a-zA-Z0-9_.:-]{8,100}$/.test(p.requestId) && (!p.planId || /^[a-zA-Z0-9_.:-]{1,100}$/.test(p.planId)) ? { requestId: p.requestId, ...(p.planId ? { planId: p.planId } : {}), ...(p.startPlanId && p.startPlanId === p.planId ? { startPlanId: p.startPlanId } : {}), ...(p.submitAttempt === true ? { submitAttempt: true as const } : {}) } : null; } catch { return null; } });
  const rebindActive = useRef(false); const observationGeneration = useRef(0);
  const [sessionCatalog, setSessionCatalog] = useState<PersonalSession[]>([]); const [rebindPending, setRebindPending] = useState(false);
  const rebindChanged = useCallback((value: boolean) => { rebindActive.current = value; setRebindPending(value); }, []);
  const [connections, setConnections] = useState<UserConnection[]>([]); const [selected, setSelected] = useState(connectionRef ?? '');
  const [connectionNames, setConnectionNames] = useState<Record<string, string>>({});
  const [project, setProject] = useState<PersonalProject>(); const [sessions, setSessions] = useState<PersonalSession[]>([]); const [session, setSession] = useState<PersonalSession>();
  const [ownerSubmit, setOwnerSubmit] = useState(false);
  const [ready, setReady] = useState(false); const [resourceReady, setResourceReady] = useState(false); const [busy, setBusy] = useState(''); const [notice, setNotice] = useState('');
  const [title, setTitle] = useState(''); const [newGoal, setNewGoal] = useState(''); const followup = useRef<{ requestId: string; text: string; epoch: number } | null>(null); const [text, setText] = useState(''); const [plan, setPlan] = useState<Plan>(); const [action, setAction] = useState<PersonalAction>();
  const [allowed, setAllowed] = useState(false); const [showReview, setShowReview] = useState(false); const [job, setJob] = useState<FactoryJob>(); const [revision, refresh] = useState(0);
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
      setConnectionNames(Object.fromEntries(refs.map(ref => { const remote = remotes.find(r => r.registrationRef === ref.registrationRef && r.providerId === provider); return [ref.ref, remote ? `${remote.origin} · 项目 ${remote.projectId || '未指定'} · ${ref.ref.slice(0, 8)}` : `连接 ${ref.ref}`]; })));
      const usable = refs.filter(r => personal.has(r.registrationRef) && r.kind === (namespace === 'opencode' ? 'environment' : 'orx') && r.status === 'active' && r.available && r.taskId === null && r.capabilities.includes('session:read'));
      setConnections(usable); setOwnerSubmit(namespace === 'native-openresearch' && cap.ownerSubmit === '/api/factory/personal-agent/commands/submit' && cap.modelConfiguration === 'remote-configured-model' && cap.factoryBYOKForwarded === false);
      if (namespace === 'native-openresearch') {
        const saved = localStorage.getItem(selectionStorage); const previous = history.find(item => item.id === saved && item.namespace === namespace && usable.some(c => c.ref === item.connectionRef));
        if (previous) { setSelected(previous.connectionRef); setSession(previous); }
        else if (usable.length === 1) setSelected(value => value || usable[0].ref);
      }
      setReady(true);
    }).catch(() => { if (!ctrl.signal.aborted) { setConnections([]); setNotice('个人会话功能尚未启用或身份无法核对。旧只读连接不会自动升级。'); } });
    return () => ctrl.abort();
  }, [ownerId, namespace, provider, revision]);
  useEffect(() => {
    const ctrl = new AbortController(); setResourceReady(false); setProject(undefined); setSessions([]); setSession(current => current?.connectionRef === selected ? current : undefined); setNativeSessions([]);
    if (ready && connections.some(c => c.ref === selected)) {
      void Promise.all([personalAgentApi.project(selected, ctrl.signal), personalAgentApi.sessions(selected, ctrl.signal), namespace === 'native-openresearch' ? personalAgentApi.nativeSessions(selected, ctrl.signal) : Promise.resolve(null)]).then(([p, s, native]) => {
        if (!ctrl.signal.aborted) { if (p.namespace !== namespace || s.some(item => item.namespace !== namespace || item.connectionRef !== selected || item.nativeProjectId !== p.nativeProjectId)) throw new Error('scope'); if (native && (native.namespace !== namespace || native.nativeProjectId !== p.nativeProjectId)) throw new Error('scope'); setProject(p); setSessions(s); if (native) setNativeSessions(native.sessions); setResourceReady(true); }
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
  async function submit(next: PersonalAction) {
    if (!ownerSubmit || disabled || rebindActive.current || !project || next !== 'create' && (!sessionWritable || !session?.nativeSessionId || !session.connectionPin?.capabilities.includes(`session:${next}`)) || next === 'prompt' && (!text.trim() || session?.activeRequestId)) return;
    const epoch = navigation.current;
    await act('submit', async () => {
      const who = await api.session(); if (!current(epoch) || who.id !== ownerId) return;
      const requestId = crypto.randomUUID(); remember({ requestId, submitAttempt: true });
      const intent: PersonalIntent = next === 'create' ? { requestId, action: next, connectionRef: selected, nativeProjectId: project.nativeProjectId, title: title.trim() || 'Factory personal session' } : next === 'prompt' ? { requestId, action: next, sessionId: session!.id, text } : { requestId, action: next, sessionId: session!.id };
      const result = await personalAgentApi.submit(intent); if (!current(epoch)) return;
      if (result.ownerId !== ownerId) throw new Error('owner');
      remember({ requestId, planId: result.planId, startPlanId: result.planId, submitAttempt: true }); setJob(result); if (next === 'prompt') setText('');
      setNotice('已提交到原生 OpenResearch。正在读取原请求进度与回复；不会自动重发。');
    });
  }
  async function createAndSubmit() {
    if (!ownerSubmit || !canCreate || disabled || !project || !newGoal.trim() || rebindActive.current) return;
    const epoch = navigation.current;
    await act('submit', async () => {
      const who = await api.session(); if (!current(epoch) || who.id !== ownerId) return;
      const journey = crypto.randomUUID(); const requestId = `${journey}:create`;
      remember({ requestId, submitAttempt: true });
      // The goal stays in memory. Reload can recover creation, but cannot resend a goal.
      followup.current = { requestId: `${journey}:prompt`, text: newGoal, epoch };
      const created = await personalAgentApi.submit({ requestId, action: 'create', connectionRef: selected, nativeProjectId: project.nativeProjectId, title: title.trim() || 'Research session' });
      if (!current(epoch)) return;
      if (created.ownerId !== ownerId) throw new Error('owner');
      remember({ requestId, planId: created.planId, startPlanId: created.planId, submitAttempt: true }); setJob(created);
      setNotice('正在确认新会话；取得原生会话回执后才提交你此次输入的研究目标。');
    });
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
      remember({ requestId, planId: result.plan.id }); setPlan(result.plan); setAction(next); setAllowed(false); setShowReview(true); setText(''); setNotice('固定命令方案已准备，尚未启动远程命令。');
    });
  }
  async function start() {
    if (rebindActive.current || !plan || plan.status !== 'ready' || !pending || pending.startPlanId || !allowed || lock.current) return;
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
      setPlan(result.plan); setJob(result.job ?? undefined); setAllowed(false);
      if (!result.job) {
        if (pending.startPlanId || pending.submitAttempt) { setShowReview(false); setNotice('原启动结果仍未知；尚未找到任务不代表没有启动。请保留原请求继续核对，不重放命令。'); }
        else { remember({ requestId: pending.requestId, planId: result.plan.id }); setShowReview(true); setNotice('原方案已找到；没有自动启动。请重新审阅并单独确认。'); }
      }
      else {
        remember({ requestId: pending.requestId, planId: result.plan.id, startPlanId: result.plan.id, ...(pending.submitAttempt ? { submitAttempt: true as const } : {}) }); setShowReview(false);
        if (result.receipt) {
          setSession(result.receipt.session); localStorage.setItem(selectionStorage, result.receipt.session.id);
          if (result.receipt.state !== 'ack_unknown') {
            const next = followup.current; followup.current = null;
            const createdSession = result.receipt.session;
            if (result.receipt.action === 'create' && next && current(next.epoch) && createdSession.nativeSessionId && !createdSession.activeRequestId && connections.some(c => c.ref === createdSession.connectionRef && c.fingerprint === createdSession.connectionPin?.fingerprint && c.capabilities.includes('session:prompt'))) {
              remember({ requestId: next.requestId, submitAttempt: true }); setNewGoal('');
              const prompted = await personalAgentApi.submit({ requestId: next.requestId, action: 'prompt', sessionId: createdSession.id, text: next.text });
              if (!current(epoch)) return;
              if (prompted.ownerId !== ownerId) throw new Error('owner');
              remember({ requestId: next.requestId, planId: prompted.planId, startPlanId: prompted.planId, submitAttempt: true }); setJob(prompted); setNotice('已确认原生会话，并提交此次研究目标。正在读取原请求进度与回复。');
            } else { remember(null); setPlan(undefined); setNotice(result.receipt.action === 'create' ? '原生会话已确认。若页面曾刷新或离开，研究目标尚未发送；请在此会话输入并提交。' : '原命令回执已核对。远程停止仍未经证实；下一轮须等待原回复观察完成。'); }
          }
          else { followup.current = null; setNotice('原远程命令确认未知。保留原请求，不自动重放；请在远程服务核对。'); }
        } else setNotice('已找到原 Factory 命令任务，远程回执尚未就绪。请稍后继续核对原请求。');
      }
    });
  }
  useEffect(() => {
    if (!ready || !pending?.submitAttempt) return;
    const timer = setInterval(() => { if (!lock.current) void recover(); }, 2000);
    return () => clearInterval(timer);
  }, [ready, pending?.requestId, pending?.submitAttempt, pending?.planId]);
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
      localStorage.removeItem(attachStorage); setAttachment(null); setSession(result.session); localStorage.setItem(selectionStorage, result.session.id); setSessions(all => [...all.filter(item => item.id !== result.session.id), result.session]); setNotice('原生会话已只读关联。可以提交研究目标或请求中断。');
    });
  }
  async function recoverAttach() {
    if (!attachment || lock.current) return; const epoch = navigation.current;
    await act('recover-attach', async () => {
      const who = await api.session(); if (!current(epoch) || who.id !== ownerId) return;
      const result = checkAttachment(await personalAgentApi.recoverAttachment(attachment.requestId), attachment, namespace);
      if (!current(epoch)) return;
      localStorage.removeItem(attachStorage); setAttachment(null); setSession(result.session); localStorage.setItem(selectionStorage, result.session.id); setSessions(all => [...all.filter(item => item.id !== result.session.id), result.session]); setNotice('已核对原只读关联请求；未重放关联或发送消息。');
    });
  }
  function closeReview() { navigation.current++; setShowReview(false); setAllowed(false); setBusy(''); setNotice('已关闭审阅，未因此启动命令。原请求保留，可继续核对。'); }
  const disabled = !!busy || !!pending || !!attachment || rebindPending || !resourceReady;
  const sessionWritable = session && connections.some(item => item.ref === session.connectionRef && !!session.connectionPin && item.fingerprint === session.connectionPin.fingerprint) && (!session.bindingStatus || session.bindingStatus === 'active');
  const visibleSessions = [...new Map([...sessionCatalog, ...sessions].map(item => [item.id, item])).values()];
  const canCreate = connections.find(c => c.ref === selected)?.capabilities.includes('session:create') === true && (namespace === 'opencode' || project?.sessionCreationSupported === true);
  return <section className="personal-session-workspace" aria-label={`个人 ${engine} 会话`}><h2>{namespace === 'native-openresearch' ? '选择项目与研究会话' : '个人远程会话'}</h2><p>普通模式：连接已有 {engine} 服务，使用它原有的项目与会话。模型密钥留在远程端，无需在 Factory 输入。</p>
    <details className="technical-detail"><summary>模型与执行范围</summary><p>{warning}</p><p>{namespace === 'opencode' ? '这是 OpenCode 原生会话，不是 upstream ORX 项目。' : '这是已有 OpenResearch 项目与原生会话；不是受管单轮文本探测。'}不代表完整科研流程验收或真实端到端兼容性验证。</p></details>
    {notice && <p role="status">{notice}</p>}
    <label>{namespace === 'native-openresearch' ? '我的 OpenResearch 项目' : '个人会话资源'}<select aria-label="个人会话资源" disabled={!ready || !!busy || !!pending || !!attachment || rebindPending} value={selected} onChange={e => { navigation.current++; setSelected(e.target.value); setPlan(undefined); setText(''); }}><option value="">选择已明确绑定的个人资源</option>{connections.map(c => <option key={c.ref} value={c.ref}>{connectionNames[c.ref] ?? `连接 ${c.ref}`}</option>)}</select></label>
    {ready && !connections.length && <div className="state-note"><strong>先连接自己的 {engine} 项目</strong><p>在资源设置中选择 {engine}，填写服务地址、原生项目 ID 与远端账户凭据，验证后绑定。设置一次后，在此选择会话并提交研究目标。旧只读绑定不会获得执行能力。</p>{onResources && <button className="primary" onClick={onResources}>设置 {engine} 连接</button>}</div>}
    <div className="personal-session-history" aria-label="已关联会话">{visibleSessions.map(s => <button key={s.id} disabled={!!busy || !!pending || !!attachment || rebindPending} onClick={() => { navigation.current++; localStorage.setItem(selectionStorage, s.id); setSession(s); setSelected(s.connectionRef); setText(''); }}>打开 {engine} 会话 {s.nativeSessionId ?? '创建确认未知'}</button>)}</div>
    {project && <><p>{engine} 原生项目 ID：{project.nativeProjectId}</p>{canCreate && <details open={namespace === 'opencode'} className="technical-detail"><summary>新建研究会话</summary><label>新会话标题<input aria-label="新会话标题" maxLength={120} value={title} disabled={disabled} onChange={e => setTitle(e.target.value)} /></label>{ownerSubmit ? <><label>新会话研究目标<textarea aria-label="新会话研究目标" value={newGoal} maxLength={16000} disabled={disabled} onChange={e => setNewGoal(e.target.value)} /></label><p>在这个项目创建会话，再向该会话发送此目标。创建确认未知时会停下，不重发。</p><button className="primary" disabled={disabled || !newGoal.trim()} onClick={() => void createAndSubmit()}>创建会话并提交研究目标</button></> : <button className="secondary" disabled={disabled} onClick={() => void prepare('create')}>准备创建会话</button>}</details>}</>}
    {project && <details open={!session} className="technical-detail"><summary>选择或切换原生会话</summary><section aria-label="已有原生会话"><h3>关联已有 {engine} 会话</h3><p>只读取现有会话并保存本地关联，不创建远程会话或调用模型。{!canCreate && '此提供方当前仅支持已有会话；新会话创建未启用。'}</p>{namespace === 'opencode' && <button disabled={disabled} onClick={() => void readNative()}>读取已有原生会话</button>}{nativeSessions.map(native => <p key={native.nativeSessionId}>{native.title ?? native.nativeSessionId}<button disabled={disabled} onClick={() => void attachNative(native)}>{namespace === 'native-openresearch' ? '选择会话' : '关联原生会话'} {native.nativeSessionId}</button></p>)}</section></details>}

    {session && <article aria-label="原生会话详情"><h3>{engine} 原生会话 ID：{session.nativeSessionId ?? '确认未知'}</h3><p>项目 {session.nativeProjectId} · 状态 {session.activeRequestId ? '研究请求待核对' : sessionStates[session.state] ?? '状态待核对'}</p>
      {!sessionWritable && <p role="alert">原绑定已到期、撤销或变更，或当前无法核对。保留原结果；请重新验证资源并在下方明确续接同一原生会话。禁止用新会话代替原请求。</p>}
      {session.observation?.correlationSource && <details className="technical-detail"><summary>结果来源与验证范围</summary><p>回复关联：{session.observation.correlationSource}。精确轮次未验证；不能据此确认科学结论或远程已停止。</p></details>}
      {session.activeRequestId && <p>原消息仍待核对：{session.activeRequestId}。等待原回复完成后才能继续发送。</p>}
      <label>{namespace === 'native-openresearch' ? '研究目标' : '下一轮消息'}<textarea aria-label="下一轮消息" value={text} maxLength={16000} disabled={disabled || !sessionWritable || !session.connectionPin?.capabilities.includes('session:prompt') || !!session.activeRequestId || !session.nativeSessionId} onChange={e => setText(e.target.value)} /></label><button className="primary" disabled={disabled || !sessionWritable || !session.connectionPin?.capabilities.includes('session:prompt') || !!session.activeRequestId || !session.nativeSessionId || !text.trim()} onClick={() => void (ownerSubmit ? submit('prompt') : prepare('prompt'))}>{ownerSubmit ? '提交研究目标' : '准备发送消息'}</button><button className="secondary" disabled={disabled || !sessionWritable || !session.connectionPin?.capabilities.includes('session:interrupt') || !session.nativeSessionId} onClick={() => void (ownerSubmit ? submit('interrupt') : prepare('interrupt'))}>{ownerSubmit ? '请求中断' : '准备尽力中断'}</button>
      <h3>回复与结果</h3>{!session.observation?.messages.length && <p>提交后，进度与回复会出现在这里；也可以打开下方原命令任务。</p>}
      {session.observation?.messages.map(m => <article key={m.id}><h4>{m.role === 'assistant' ? '远程代理' : '你'} · {m.completed ? '远程报告回复完成' : '未报告完成'}</h4>{m.events.map((event, i) => event.type === 'text' ? <p key={i} style={{ whiteSpace: 'pre-wrap' }}>{event.text}</p> : <details key={i}><summary>工具 {event.tool} · {event.status}</summary><pre>{event.output}</pre></details>)}{m.role === 'assistant' && feeManagementEnabled && m.usageProvenance !== 'unavailable' && m.usage && <details className="technical-detail"><summary>远端报告的用量（未验证）</summary><pre>{JSON.stringify(m.usage)}</pre></details>}</article>)}

    </article>}
    <details open={!!session && !sessionWritable} className="technical-detail"><summary>更新连接或续接原会话</summary><PersonalSessionRebind ownerId={ownerId} namespace={namespace} session={session} candidates={connections} disabled={!!busy || !!attachment || !ready} commandPending={!!pending} onPending={rebindChanged} onRebound={next => { navigation.current++; observationGeneration.current++; setSession(next); setSelected(next.connectionRef); setSessions(all => [...all.filter(item => item.id !== next.id), next]); setSessionCatalog(all => [...all.filter(item => item.id !== next.id), next]); setText(''); setPlan(undefined); setShowReview(false); refresh(n => n + 1); }} /></details>
    {attachment && <p role="alert">原只读关联请求：{attachment.requestId}<button disabled={!!busy} onClick={() => void recoverAttach()}>核对原会话关联</button></p>}
    {pending && <p role="alert">原请求：{pending.requestId}<button disabled={!!busy} onClick={() => void recover()}>核对原会话命令</button></p>}
    {job && <p>Factory 命令任务：{job.id} · {statusNames[job.status] ?? '状态待核对'}。本地成功不证明远程已停止。{onTask && <button onClick={() => onTask(job.id)}>查看命令任务</button>}</p>}
    <button disabled={!!busy} onClick={() => { navigation.current++; setShowReview(false); setAllowed(false); refresh(n => n + 1); }}>刷新个人资源</button>
    {showReview && plan && <dialog ref={dialog} className="personal-session-dialog" role="dialog" aria-modal="true" aria-label="审阅个人会话命令" onCancel={event => { event.preventDefault(); closeReview(); }}><h3>{action === 'create' ? `创建 ${engine} 会话` : action ? labels[action] : '原个人会话命令'}：确认提交</h3><p>{warning}</p><p>{plan.status === 'ready' ? '命令就绪' : '命令范围尚未通过检查'}</p><CommandSummary plan={plan}/>{plan.missing?.length > 0 && <p>{plan.missing.join('、')}</p>}
      <PlanReviewGate ownerId={ownerId} plan={plan} busy={busy} act={act} onAllowed={setAllowed} />
      <p className="quiet">点击确认，将向上方固定项目或会话提交此命令。</p>
      <div className="button-row"><button className="primary" disabled={!!busy || !allowed || plan.status !== 'ready' || !!pending?.startPlanId} onClick={() => void start()}>确认提交此命令</button><button className="secondary" onClick={closeReview}>关闭审阅</button></div>
    </dialog>}
  </section>;
}
