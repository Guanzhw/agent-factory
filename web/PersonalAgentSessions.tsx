import './personalAgentSessions.css';
import { applicationEnvironmentApi, PLATFORM_ORX_PROVIDER, SSH_ORX_PROVIDER, type OwnedServer, type ApplicationEnvironment } from './applicationEnvironmentApi.js';
import { ownerModelApi } from './ownerModelApi.js';
import { researchStatus, researchReplyFailed } from './researchStatus.js';
import { PersonalOrxProjects } from './PersonalOrxProjects.js';
import { OpenResearchSetup } from './OpenResearchSetup.js';
import { PersonalSessionRebind } from './PersonalSessionRebind.js';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useFeeManagement } from './FeeVisibility.js';
import { api, ApiError } from './api.js';
import { PlanReviewGate } from './PlanReviews.js';
import { personalRemoteApi, definitivelyRejected } from './personalRemoteApi.js';
import { PERSONAL_CONTRACT, PERSONAL_PROVIDER, ORX_PERSONAL_PROVIDER, personalAgentApi, checkPersonalRecovery, checkAttachment, type PersonalAttachment, type NativePersonalSession, type PersonalNamespace, type PersonalAction, type PersonalIntent, type PersonalProject, type PersonalSession } from './personalAgentApi.js';
import { statusNames, type FactoryJob, type Plan, type UserConnection } from './models.js';

type Props = { onResources?: () => void; ownerId: string; onTask?: (id: string) => void; connectionRef?: string; namespace?: PersonalNamespace; researchJourney?: boolean; onModels?: () => void };
type Pending = { requestId: string; planId?: string; startPlanId?: string; submitAttempt?: true };
const labels = { create: '创建 OpenCode 会话', prompt: '发送下一轮消息', interrupt: '请求尽力中断' };
const warning = '会话使用远程服务的模型配置。中断仅尽力而为，停止状态以服务端记录为准。';
const sessionStates: Record<string, string> = { ready: '可准备消息', result_observed: '已观察到远程回复', ack_unknown: '命令回执未确认', create_ack_unknown: '会话创建回执未确认', pending: '等待回执', creating: '等待创建确认' };
function isLeasePreAdmissionRejection(error: ApiError) {
  return error.status === 409 && ['ORX_LEASE_EXPLICIT_SELECTION_REQUIRED', 'REMOTE_CREDENTIAL_UNAVAILABLE', 'ORX_LEASE_PRE_ADMISSION_HEALTH_CHECK_FAILED'].includes(error.code ?? '');
}
function CommandSummary({ plan }: { plan: Plan }) {
  const values = plan.inputValues ?? {};
  const text = (key: string) => typeof values[key] === 'string' && values[key] ? values[key] as string : '未提供';
  const action = text('action');
  return <section className="personal-command-summary" aria-label="此次固定命令范围"><h4>此次固定命令范围</h4><dl className="plan-details"><dt>动作</dt><dd>{({ create: '创建原生会话', prompt: '发送下一轮消息', interrupt: '请求尽力中断' } as Record<string, string>)[action] ?? '动作未确认，请核对技术快照'}</dd><dt>原生项目 ID</dt><dd>{text('nativeProjectId')}</dd>{action === 'create' ? <><dt>新会话标题</dt><dd>{text('title')}</dd></> : <><dt>原生会话 ID</dt><dd>{text('nativeSessionId')}</dd></>}</dl>{action === 'prompt' && <><h4>将发送的消息</h4><p className="personal-command-text">{text('text')}</p></>}{action === 'interrupt' && <p>仅向原会话请求中断，不证明工具、模型或远端进程已停止。</p>}<details className="technical-detail"><summary>固定方案与连接技术快照</summary><span>方案 {plan.id}</span><pre>{JSON.stringify(values, null, 2)}</pre></details></section>;
}
export function PersonalAgentSessions(props: Props) { return <PersonalSessions key={`${props.ownerId}:${props.namespace ?? 'opencode'}`} {...props} />; }
function PersonalSessions({ ownerId, onTask, onResources, connectionRef, namespace = 'opencode', researchJourney = false, onModels }: Props) {
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
  const draftStorage = `factory-research-draft:${encodeURIComponent(ownerId)}`;
  const readDraft = () => { try { const d = JSON.parse(sessionStorage.getItem(draftStorage) ?? '{}'); return { goal: typeof d.goal === 'string' ? d.goal.slice(0, 16000) : '', materials: typeof d.materials === 'string' ? d.materials.slice(0, 16000) : '' }; } catch { return { goal: '', materials: '' }; } };
  const [researchGoal, setResearchGoal] = useState(() => researchJourney ? readDraft().goal : '');
  const [materials, setMaterials] = useState(() => researchJourney ? readDraft().materials : '');
  const [revision, refresh] = useState(0);
  const locationChosen = useRef(false);
  const environmentStorage = `factory-environment-prepare:${encodeURIComponent(ownerId)}`;
  const [platformAvailable, setPlatformAvailable] = useState(false);
  const [location, setLocation] = useState<'platform' | 'ssh' | 'existing'>('existing');
  const [sshAvailable, setSshAvailable] = useState(false);
  const [ownedServers, setOwnedServers] = useState<OwnedServer[]>([]);
  const [serverRef, setServerRef] = useState(''); const [serverDirectory, setServerDirectory] = useState('');
  const [environmentSelectionRejected, setEnvironmentSelectionRejected] = useState(false);
  function editEnvironmentSelection() {
    if (environmentSelectionRejected) { setEnvironmentSelectionRejected(false); setNotice(''); }
  }
  const managedAvailable = platformAvailable || sshAvailable;
  const managedLocation = location !== 'existing';
  const environmentLabel = location === 'ssh' ? '服务器环境' : '平台环境';
  const [modelConfigured, setModelConfigured] = useState(false);
  const [environment, setEnvironment] = useState<ApplicationEnvironment>();
  const [environmentRequest, setEnvironmentRequest] = useState(() => { try { const value = localStorage.getItem(environmentStorage); return value && /^[a-zA-Z0-9_.:-]{8,80}$/.test(value) ? value : ''; } catch { return ''; } });
  useEffect(() => {
    if (!researchJourney) return;
    const ctrl = new AbortController();
    void Promise.all([applicationEnvironmentApi.capabilities(ctrl.signal), ownerModelApi.list(ownerId, ctrl.signal)]).then(([cap, models]) => {
      if (ctrl.signal.aborted) return;
      const available = cap.locations.includes('platform') && cap.applications.includes('openresearch');
      setPlatformAvailable(available); if (!locationChosen.current) setLocation(available ? 'platform' : 'existing');
      setModelConfigured(models.some(model => model.isDefault && model.available));
      setSshAvailable(cap.locations.includes('ssh') && cap.applications.includes('openresearch'));
      if (cap.locations.includes('ssh')) void applicationEnvironmentApi.servers(ctrl.signal).then(servers => {
        if (ctrl.signal.aborted) return; setOwnedServers(servers);
        setServerRef(previous => previous || servers[0]?.reference || '');
        setServerDirectory(previous => previous || servers[0]?.defaultDirectory || '');
        if (!available && !locationChosen.current && servers.length) setLocation('ssh');
      }).catch(() => { if (!ctrl.signal.aborted) { setSshAvailable(false); setOwnedServers([]); } });
    }).catch(() => { if (!ctrl.signal.aborted) { setPlatformAvailable(false); setSshAvailable(false); } });
    // Recovery reads custody only. It cannot resume this click's goal submission.
    if (environmentRequest) void applicationEnvironmentApi.recover(environmentRequest, ctrl.signal).then(result => {
      if (!ctrl.signal.aborted) { setEnvironment(result.environment);
        if (result.environment.location === 'ssh') { locationChosen.current = true; setLocation('ssh'); setServerRef(result.environment.serverRef || ''); setServerDirectory(result.environment.remoteDirectory || ''); }
        setNotice('已核对原环境准备请求；研究目标没有因此发送。准备确认后，请明确点击开始研究。'); }
    }).catch(() => { if (!ctrl.signal.aborted) setNotice('环境准备尚未确认。目标草稿保留，请核对原准备请求。'); });
    return () => ctrl.abort();
  }, [ownerId, researchJourney, revision]);
  const [setupOpen, setSetupOpen] = useState(false);
  const [projectSetupOpen, setProjectSetupOpen] = useState(false);
  const [creationConnection, setCreationConnection] = useState('');
  const [creationRevision, refreshCreationConnections] = useState(0);
  const projectSetupElement = useRef<HTMLDetailsElement>(null);
  const researchText = materials.trim() ? `${researchGoal.trim()}\n\n补充材料（用户提供）：\n${materials.trim()}` : researchGoal.trim();
  useEffect(() => { if (researchJourney) { try { sessionStorage.setItem(draftStorage, JSON.stringify({ goal: researchGoal, materials })); } catch { /* In-memory draft remains; dispatch still requires durable request storage. */ } } }, [researchJourney, draftStorage, researchGoal, materials]);
  const [title, setTitle] = useState(''); const [newGoal, setNewGoal] = useState(''); const followup = useRef<{ requestId: string; text: string; epoch: number } | null>(null); const [text, setText] = useState(''); const [plan, setPlan] = useState<Plan>(); const [action, setAction] = useState<PersonalAction>();
  const [allowed, setAllowed] = useState(false); const [showReview, setShowReview] = useState(false); const [job, setJob] = useState<FactoryJob>();
  const dialog = useRef<HTMLDialogElement>(null);
  const live = useRef(true); const lock = useRef(false); const navigation = useRef(0);
  useEffect(() => { live.current = true; return () => { live.current = false; navigation.current++; }; }, []);
  useEffect(() => {
    const element = dialog.current; if (!showReview || !element) return;
    element.showModal(); return () => { element.close(); };
  }, [showReview, plan?.id]);
  const current = (epoch: number) => live.current && navigation.current === epoch;
  function identityChanged() {
    if (researchJourney) { followup.current = null; setResearchGoal(''); setMaterials(''); setSession(undefined); setConnections([]); setSessionCatalog([]); setReady(false); setNotice('登录账户已变化，请刷新后继续。'); }
  }
  async function ownerIsCurrent(epoch: number) {
    const who = await api.session();
    if (!current(epoch)) return false;
    if (who.id !== ownerId) { identityChanged(); return false; }
    return true;
  }
  function remember(p: Pending | null) { if (p) localStorage.setItem(storage, JSON.stringify(p)); else localStorage.removeItem(storage); setPending(p); }
  function handleSubmitRejection(error: unknown, epoch: number, creating = false) {
    if (!current(epoch) || !(error instanceof ApiError)) return false;
    const leaseRejected = researchJourney && isLeasePreAdmissionRejection(error);
    if (!definitivelyRejected(error.status) && !leaseRejected) return false;
    remember(null); followup.current = null;
    if (error.code === 'EXPECTED_OWNER_MISMATCH') { identityChanged(); return true; }
    setNotice(error.code === 'ORX_LEASE_PRE_ADMISSION_HEALTH_CHECK_FAILED'
      ? '研究未提交：连接健康检查暂时失败，草稿和原回复保留。恢复后可明确重试；原请求不会重发。'
      : creating ? '研究未启动：请检查连接或当前权限，草稿保留。'
      : '研究未提交：原请求不会重发，草稿保留。若连接授权或目标变化，请明确选择连接；原轮次仍未知时先核对它。');
    if (leaseRejected) setSetupOpen(true);
    return true;
  }
  function adoptSession(next: PersonalSession) {
    setSession(next);
    if (researchJourney && next.bindingStatus === 'active' && next.connectionPin?.ownerId === ownerId) {
      setSelected(next.connectionRef);
      const pin = next.connectionPin;
      setConnections(all => [...all.filter(item => item.ref !== pin.ref), pin]);
    }
  }
  async function continueViewing() {
    if (!session?.nativeSessionId || !!busy || rebindActive.current) return; const epoch = navigation.current;
    await act('continue', async () => {
      if (!await ownerIsCurrent(epoch)) return;
      try {
        const resumed = await personalAgentApi.continueResearch(session);
        if (!current(epoch)) return;
        adoptSession(resumed.session);
        setNotice(resumed.state === 'ready' ? '已继续原研究。结果和原请求保留，可以追问。' : '仍在等待原研究的明确回复；已核对原连接，不会重发研究请求。');
      } catch (error) {
        if (current(epoch) && error instanceof ApiError && error.status === 409) { setNotice('原连接的授权或目标无法保持一致，请明确选择研究连接。结果和草稿保留。'); setSetupOpen(true); return; } throw error;
      }
    });
  }
  useEffect(() => {
    const ctrl = new AbortController(); setReady(false);
    void Promise.all([api.session(ctrl.signal), personalAgentApi.capabilities(ctrl.signal), api.userConnections(ctrl.signal), personalRemoteApi.list(ctrl.signal), personalAgentApi.sessions(undefined, ctrl.signal)]).then(async ([who, cap, refs, remotes, history]) => {
      if (ctrl.signal.aborted) return;
      if (who.id !== ownerId || cap.executionContract !== PERSONAL_CONTRACT || cap.nativeQueue !== true || refs.some(r => r.ownerId !== ownerId)) throw new Error('identity');
      setSessionCatalog(history.filter(item => item.namespace === namespace));
      const personal = new Set(remotes.filter(r => r.providerId === provider || namespace === 'native-openresearch' && [PLATFORM_ORX_PROVIDER, SSH_ORX_PROVIDER].includes(r.providerId)).map(r => r.registrationRef));
      setConnectionNames(Object.fromEntries(refs.map(ref => { const remote = remotes.find(r => r.registrationRef === ref.registrationRef && (r.providerId === provider || namespace === 'native-openresearch' && [PLATFORM_ORX_PROVIDER, SSH_ORX_PROVIDER].includes(r.providerId))); return [ref.ref, remote?.providerId === SSH_ORX_PROVIDER ? '我的服务器 · 原生 OpenResearch' : remote?.providerId === PLATFORM_ORX_PROVIDER ? '平台环境 · 原生 OpenResearch' : remote ? `${remote.origin} · 项目 ${remote.projectId || '未指定'} · ${ref.ref.slice(0, 8)}` : `连接 ${ref.ref}`]; })));
      const usable = refs.filter(r => personal.has(r.registrationRef) && r.kind === (namespace === 'opencode' ? 'environment' : 'orx') && (r.status === 'active' && r.available || researchJourney && r.status === 'expired') && r.taskId === null && r.capabilities.includes('session:read'));
      setConnections(usable); setOwnerSubmit(namespace === 'native-openresearch' && cap.ownerSubmit === '/api/factory/personal-agent/commands/submit' && cap.modelConfiguration === 'remote-configured-model' && cap.factoryBYOKForwarded === false);
      if (namespace === 'native-openresearch') {
        const saved = localStorage.getItem(selectionStorage); const previous = history.find(item => item.id === saved && item.namespace === namespace && (researchJourney || usable.some(c => c.ref === item.connectionRef)));
        if (previous && !connectionRef) { setSelected(previous.connectionRef); setSession(previous); }
        else if (usable.length === 1 || researchJourney) {
          const preferred = usable.find(c => c.ref === selected) ?? usable.find(c => c.available) ?? usable.find(c => c.capabilities.includes('session:create')) ?? usable[0];
          if (researchJourney && preferred?.status === 'expired' && cap.ownerSubmit && !pending && !attachment) {
            try {
              const renewed = await personalAgentApi.refreshConnection(preferred);
              if (ctrl.signal.aborted) return;
              setConnections([...usable.filter(c => c.ref !== preferred.ref), renewed]); setSelected(renewed.ref);
            } catch { if (!ctrl.signal.aborted) { setNotice('暂时无法使用原研究连接。请重试；若授权或目标已变化，请明确选择连接。草稿保留。'); setSetupOpen(true); } }
          } else setSelected(preferred?.ref ?? '');
        }
      }
      setReady(true);
    }).catch(() => { if (!ctrl.signal.aborted) { setConnections([]); setNotice('个人会话功能尚未启用或身份无法核对。旧只读连接不会自动升级。'); } });
    return () => ctrl.abort();
  }, [ownerId, namespace, provider, revision, researchJourney, connectionRef]);
  useEffect(() => {
    const ctrl = new AbortController(); setResourceReady(false); setProject(undefined); setSessions([]); setSession(current => current?.connectionRef === selected ? current : undefined); setNativeSessions([]);
    if (ready && connections.some(c => c.ref === selected && c.available)) {
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
      try { const result = await personalAgentApi.session(sessionId!, ctrl.signal); if (!ctrl.signal.aborted && generation === observationGeneration.current) { if (result.namespace !== namespace || result.connectionPin?.ownerId !== ownerId) throw new Error('namespace'); setSession(result); if (researchJourney && (result.state === 'result_observed' && !result.activeRequestId || researchReplyFailed(result.observation?.messages.at(-1)))) setNotice(value => value.startsWith('原消息已受理') || value.startsWith('已确认原生会话，并提交') || value.startsWith('已提交到原生 OpenResearch') || value.startsWith('Factory 已受理原命令') || value.startsWith('原生会话已确认；Factory') ? '' : value); } }
      catch {
        if (!ctrl.signal.aborted && generation === observationGeneration.current) {
          try { const snapshot = await personalAgentApi.snapshot(sessionId!, ctrl.signal); if (!ctrl.signal.aborted && generation === observationGeneration.current && snapshot.connectionPin?.ownerId === ownerId && snapshot.namespace === namespace) setSession(snapshot); }
          catch { if (!ctrl.signal.aborted) setSession(current => current && current.id === sessionId ? { ...current, bindingStatus: 'unavailable' } : current); }
          if (!ctrl.signal.aborted) setNotice('研究结果和原请求已保留。继续研究时会检查原连接；无法确认授权或目标时会停止。');
        }
      }
      if (!ctrl.signal.aborted) timer = setTimeout(() => void poll(), 4000);
    }
    void poll(); return () => { ctrl.abort(); clearTimeout(timer); };
  }, [sessionId, namespace, session?.connectionPin?.fingerprint]);
  async function act(name: string, work: () => Promise<void>) {
    if (lock.current) return; lock.current = true; setBusy(name); const epoch = navigation.current;
    try { await work(); } catch (error) { if (current(epoch)) { if (researchJourney && error instanceof ApiError && (error.status === 401 || error.code === 'EXPECTED_OWNER_MISMATCH')) identityChanged(); else setNotice('结果尚未确认。请核对原请求，不会自动提交新的请求或重放远程命令。'); } }
    finally { lock.current = false; if (current(epoch)) setBusy(''); }
  }
  async function submit(next: PersonalAction) {
    if (researchJourney && researchText.length > 16000 || !ownerSubmit || disabled || rebindActive.current || !project && !researchJourney || next !== 'create' && (!sessionWritable && !(next === 'prompt' && leaseContinuation) || !session?.nativeSessionId || !session.connectionPin?.capabilities.includes(`session:${next}`)) || next === 'prompt' && (!(researchJourney ? researchText : text).trim() || session?.activeRequestId)) return;
    const epoch = navigation.current;
    await act('submit', async () => {
      if (!await ownerIsCurrent(epoch)) return;
      const requestId = crypto.randomUUID(); remember({ requestId, submitAttempt: true });
      const intent: PersonalIntent = next === 'create' ? { requestId, action: next, connectionRef: selected, nativeProjectId: project!.nativeProjectId, title: title.trim() || 'Factory personal session' } : next === 'prompt' ? { requestId, action: next, sessionId: session!.id, text: researchJourney ? researchText : text } : { requestId, action: next, sessionId: session!.id };
      let result;
      try { result = await personalAgentApi.submit(intent, ...(researchJourney ? [ownerId] : [])); } catch (error) {
        if (handleSubmitRejection(error, epoch)) return;
        throw error;
      }
      if (!current(epoch)) return;
      if (result.ownerId !== ownerId) throw new Error('owner');
      remember({ requestId, planId: result.planId, startPlanId: result.planId, submitAttempt: true }); setJob(result); if (next === 'prompt') { setText(''); if (researchJourney) { setResearchGoal(''); setMaterials(''); } }
      setNotice('Factory 已受理原命令，远端回执与回复仍待核对；不会自动重发。');
    });
  }
  async function createAndSubmit() {
    if (researchJourney && researchText.length > 16000 || !ownerSubmit || !canCreate || disabled || !project || !(researchJourney ? researchText : newGoal).trim() || rebindActive.current) return;
    const epoch = navigation.current;
    await act('submit', async () => {
      if (!await ownerIsCurrent(epoch)) return;
      await submitNewSession(selected, project.nativeProjectId, researchJourney ? researchText : newGoal, researchJourney ? researchGoal.trim().slice(0, 120) : title.trim() || 'Research session', epoch);
    });
  }
  async function submitNewSession(targetConnection: string, targetProject: string, goal: string, sessionTitle: string, epoch: number) {
      const journey = crypto.randomUUID(); const requestId = `${journey}:create`;
      remember({ requestId, submitAttempt: true });
      // The goal stays in memory. Reload can recover creation, but cannot resend a goal.
      followup.current = { requestId: `${journey}:prompt`, text: goal, epoch };
      let created;
      try { created = await personalAgentApi.submit({ requestId, action: 'create', connectionRef: targetConnection, nativeProjectId: targetProject, title: sessionTitle }, ...(researchJourney ? [ownerId] : [])); } catch (error) { if (handleSubmitRejection(error, epoch, true)) return; throw error; }
      if (!current(epoch)) return;
      if (created.ownerId !== ownerId) throw new Error('owner');
      remember({ requestId, planId: created.planId, startPlanId: created.planId, submitAttempt: true }); setJob(created);
      setNotice('正在确认新会话；取得原生会话回执后才提交你此次输入的研究目标。');
  }
  async function preparePlatform(submitGoal: boolean) {
    if (!managedAvailable || !managedLocation || location === 'ssh' && (!serverRef || !serverDirectory.trim()) || !ready || !ownerSubmit || pending || attachment || rebindPending || rebindActive.current || lock.current || session?.activeRequestId || submitGoal && (!researchText.trim() || researchText.length > 16000)) return;
    const epoch = navigation.current; const goal = researchText; const sessionTitle = researchGoal.trim().slice(0, 120);
    await act('environment', async () => {
      if (!await ownerIsCurrent(epoch)) return;
      setEnvironmentSelectionRejected(false);
      const requestId = crypto.randomUUID(); localStorage.setItem(environmentStorage, requestId); setEnvironmentRequest(requestId);
      setNotice(`正在准备你的${environmentLabel}；原生项目数据保留，准备请求不会发送研究目标。`);
      let result;
      try {
        result = await (location === 'ssh' ? applicationEnvironmentApi.prepare(ownerId, requestId, { location: 'ssh', serverRef, directory: serverDirectory.trim() }) : applicationEnvironmentApi.prepare(ownerId, requestId));
      } catch (error) {
        // These server responses precede persisted intent and installation. A
        // transport/acknowledgement failure retains the original recovery ID.
        if (current(epoch) && error instanceof ApiError && (error.status === 422 ||
            error.status === 409 && error.message === 'ENVIRONMENT_SSH_SELECTION_UNAVAILABLE')) {
          localStorage.removeItem(environmentStorage); setEnvironmentRequest(''); setEnvironmentSelectionRejected(true);
          setNotice('服务器或目录未通过检查。请修改已授权服务器或私有目录后再开始；尚未安装环境或发送研究目标。');
          return;
        }
        throw error;
      }
      if (!current(epoch) || !await ownerIsCurrent(epoch)) return;
      if (result.requestId !== requestId || result.environment.applicationId !== 'openresearch' || result.environment.researchSubmitted !== false) throw new Error('scope');
      setEnvironment(result.environment);
      if (result.state !== 'ready' || result.environment.state !== 'ready' || !result.environment.connectionRef) {
        setNotice('环境准备尚未确认。目标草稿保留；不会自动重试研究。请核对原准备请求后明确恢复环境。'); return;
      }
      const ref = result.environment.connectionRef; const native = await personalAgentApi.project(ref);
      if (!current(epoch) || !await ownerIsCurrent(epoch)) return;
      if (native.namespace !== 'native-openresearch' || native.nativeProjectId !== result.environment.projectId || native.modelCredentialCustody !== 'owner-vault' || !native.sessionCreationSupported) throw new Error('scope');
      localStorage.removeItem(environmentStorage); setEnvironmentRequest('');
      setSelected(ref); setProject(native); setResourceReady(true);
      if (submitGoal) await submitNewSession(ref, native.nativeProjectId, goal, sessionTitle, epoch);
      else { refresh(n => n + 1); setNotice(`${environmentLabel}已就绪。原研究记录保留，尚未发送目标；可以明确开始或继续研究。`); }
    });
  }
  async function recoverEnvironment() {
    if (!environmentRequest || lock.current) return;
    const epoch = navigation.current;
    await act('environment-recovery', async () => {
      if (!await ownerIsCurrent(epoch)) return;
      const result = await applicationEnvironmentApi.recover(environmentRequest);
      if (!current(epoch)) return;
      setEnvironment(result.environment);
      if (result.environment.location === 'ssh') { locationChosen.current = true; setLocation('ssh'); setServerRef(result.environment.serverRef || ''); setServerDirectory(result.environment.remoteDirectory || ''); }
      setNotice('已核对原环境准备状态；没有发送或重发研究目标。');
    });
  }
  async function prepare(next: PersonalAction) {
    if (next !== 'create' && (!sessionWritable || !session?.connectionPin?.capabilities.includes(`session:${next}`))) return;
    if (!ready || !resourceReady || pending || attachment || rebindPending || rebindActive.current || lock.current || !project || next !== 'create' && !session?.nativeSessionId || next === 'prompt' && (!(researchJourney ? researchText : text).trim() || session?.activeRequestId)) return;
    const epoch = navigation.current;
    await act('prepare', async () => {
      if (!await ownerIsCurrent(epoch)) return;
      const requestId = crypto.randomUUID(); remember({ requestId });
      const intent: PersonalIntent = next === 'create' ? { requestId, action: next, connectionRef: selected, nativeProjectId: project.nativeProjectId, title: title.trim() || 'Factory personal session' } : next === 'prompt' ? { requestId, action: next, sessionId: session!.id, text: researchJourney ? researchText : text } : { requestId, action: next, sessionId: session!.id };
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
      if (!await ownerIsCurrent(epoch)) return;
      remember({ ...pending, startPlanId: plan.id }); setAllowed(false);
      const result = await personalAgentApi.start(plan.id); if (!current(epoch)) return;
      if (result.ownerId !== ownerId) throw new Error('owner');
      setJob(result); setShowReview(false); setNotice('Factory 命令任务已接收。任务完成只表示远程命令受理或观察完成，不证明远程已停止。请核对原请求。');
    });
  }
  async function recover() {
    if (!pending || lock.current) return; const epoch = navigation.current;
    await act('recover', async () => {
      if (!await ownerIsCurrent(epoch)) return;
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
          adoptSession(result.receipt.session); localStorage.setItem(selectionStorage, result.receipt.session.id);
          if (result.receipt.state !== 'ack_unknown') {
            const next = followup.current; followup.current = null;
            const createdSession = result.receipt.session;
            if (result.receipt.action === 'create' && next && current(next.epoch) && createdSession.nativeSessionId && !createdSession.activeRequestId && createdSession.connectionPin?.ownerId === ownerId && createdSession.connectionPin.capabilities.includes('session:prompt')) {
              remember({ requestId: next.requestId, submitAttempt: true }); setNewGoal('');
              if (!await ownerIsCurrent(epoch)) return;
              let prompted;
              try { prompted = await personalAgentApi.submit({ requestId: next.requestId, action: 'prompt', sessionId: createdSession.id, text: next.text }, ...(researchJourney ? [ownerId] : [])); }
              catch (error) { if (handleSubmitRejection(error, epoch)) return; throw error; }
              if (!current(epoch)) return;
              if (prompted.ownerId !== ownerId) throw new Error('owner');
              remember({ requestId: next.requestId, planId: prompted.planId, startPlanId: prompted.planId, submitAttempt: true }); setJob(prompted); if (researchJourney) { setResearchGoal(''); setMaterials(''); } setNotice('原生会话已确认；Factory 已受理目标命令，远端回执与回复仍待核对。');
            } else { remember(null); setPlan(undefined); setNotice(result.receipt.action === 'create' ? '原生会话已确认。若页面曾刷新或离开，研究目标尚未发送；请在此会话输入并提交。' : result.receipt.action === 'interrupt' ? '原中断请求已核对；远端进程是否停止仍需核对。' : '原消息已受理，正在读取此会话的进度与回复。下一轮须等待原回复完成。'); }
          }
          else if (['completed', 'failed', 'canceled'].includes(result.job.status) || ['completed', 'failed', 'canceled', 'cancelled', 'error', 'runstatus.completed', 'runstatus.cancelled', 'runstatus.error'].includes(String(result.nativeStatus ?? '').toLowerCase())) { followup.current = null; setNotice('原远程命令确认未知。保留原请求，不自动重放；请在远程服务核对。'); }
          else setNotice('正在等待原命令的明确回执，研究目标保留。不会重发原命令。');
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
      if (!await ownerIsCurrent(epoch)) return;
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
      if (!await ownerIsCurrent(epoch)) return;
      const result = checkAttachment(await personalAgentApi.recoverAttachment(attachment.requestId), attachment, namespace);
      if (!current(epoch)) return;
      localStorage.removeItem(attachStorage); setAttachment(null); setSession(result.session); localStorage.setItem(selectionStorage, result.session.id); setSessions(all => [...all.filter(item => item.id !== result.session.id), result.session]); setNotice('已核对原只读关联请求；未重放关联或发送消息。');
    });
  }
  function closeReview() { navigation.current++; setShowReview(false); setAllowed(false); setBusy(''); setNotice('已关闭审阅，未因此启动命令。原请求保留，可继续核对。'); }
  const leaseContinuation = researchJourney && !!session?.nativeSessionId && !!session.connectionPin?.capabilities.includes('session:prompt') && ['expired', 'changed', 'unavailable'].includes(session.bindingStatus ?? '');
  const disabled = !!busy || !!pending || !!attachment || rebindPending || !resourceReady && !leaseContinuation;
  const sessionWritable = session && connections.some(item => item.ref === session.connectionRef && !!session.connectionPin && item.fingerprint === session.connectionPin.fingerprint) && (!session.bindingStatus || session.bindingStatus === 'active');
  const visibleSessions = [...new Map([...sessionCatalog, ...sessions].map(item => [item.id, item])).values()];
  const canCreate = connections.find(c => c.ref === selected)?.capabilities.includes('session:create') === true && (namespace === 'opencode' || project?.sessionCreationSupported === true);
  if (researchJourney) {
    const answers = session?.observation?.messages.filter(m => m.role === 'assistant') ?? [];
    const latest = answers.at(-1);
    const ordinaryStatus = researchStatus({ ready, submitting: ['submit', 'start'].includes(busy), commandPending: !!pending, attachmentPending: !!attachment, session, connectionUnavailable: !!session && !sessionWritable, canRun: ownerSubmit && resourceReady && (session ? !!sessionWritable && !!session.connectionPin?.capabilities.includes('session:prompt') : canCreate) });
    const status = !session && environmentSelectionRejected ? { tone: 'failed', title: '请修正服务器或目录', explanation: '本次检查未通过，尚未安装环境或发送目标。修改选择后可以重新开始。' } : !session && environmentRequest && !busy ? { tone: 'unknown', title: '环境准备待核对', explanation: '请核对原准备请求，再明确恢复；目标草稿保留，不会重发。' } : !session && !pending && managedAvailable && managedLocation && ready ? { tone: 'neutral', title: busy === 'environment' ? `正在准备${environmentLabel}` : !modelConfigured ? '请配置自己的默认模型' : '可以开始研究', explanation: busy === 'environment' ? '正在检查原生运行包和项目；目标尚未提交。' : !modelConfigured ? '设置一次模型后，开始时会自动准备你的研究环境。' : `开始时自动准备或复用${environmentLabel}，再向原生会话发送此次目标。` } : ordinaryStatus;
    const needsSetup = ready && (!connections.length || !!project && !canCreate && !session);
    function begin() { if (!session && managedLocation && managedAvailable) { void preparePlatform(true); return; } if (session && (!session.nativeSessionId || session.state === 'create_ack_unknown')) return; if (!resourceReady && !leaseContinuation || !session && !canCreate) { setSetupOpen(true); return; } void (session ? submit('prompt') : createAndSubmit()); }
    const resultPanel = <section className="research-results" aria-label="研究结果"><div className="research-result-heading"><h2>结果与重要发现</h2>{session && <button className="secondary" disabled={disabled || !!session.activeRequestId} onClick={() => { navigation.current++; setSession(undefined); localStorage.removeItem(selectionStorage); setResearchGoal(''); setMaterials(''); }}>开始新的研究</button>}</div>
        {answers.length ? answers.map(m => <article key={m.id} className="research-answer"><p className="quiet">{researchReplyFailed(m) ? '远端记录了错误' : m.completed ? '远端回复' : '远端回复尚未完成'}</p>{m.events.filter(e => e.type === 'text').map((e, i) => e.type === 'text' && <p key={i} className="research-answer-text">{e.text}</p>)}{!m.events.some(e => e.type === 'text' && e.text.trim()) && <p>{researchReplyFailed(m) ? '本条回复没有最终研究结果。请刷新核对原会话，并查看过程详情或原任务；不会自动重发目标。' : '已观察到工具活动，但还没有可阅读的研究回复。'}</p>}</article>) : <div className="research-empty"><strong>{session?.activeRequestId || pending ? '正在等待原研究的回复' : '研究回复会出现在这里'}</strong><p>{session ? '暂未取得可阅读的结果。可刷新核对原请求，或查看过程详情。' : '输入研究目标开始；收到回复后，可以继续追问。'}</p></div>}
        {latest && <details><summary>结果来源</summary><p>来自此 OpenResearch 原生会话的远端回复。{session?.observation?.exactTurnVerified === false && '按会话记录变化关联，精确轮次未验证。'}研究结论需结合原始材料核实。</p></details>}
      </section>;
    return <section className="research-journey" aria-label="OpenResearch 研究">
      <div className="research-status" data-tone={status.tone} role="status"><span className="research-status-dot" aria-hidden="true" /><div><strong>{status.title}</strong><p className="quiet">{status.explanation}</p></div><button className="text-button" disabled={!!busy} onClick={() => { setShowReview(false); refresh(n => n + 1); }}>刷新</button></div>
      {ready && !ownerSubmit && <p role="alert">此部署暂不能直接开始普通研究。已有记录与草稿保留，请联系部署维护者启用个人命令能力。</p>}
      {session && !session.connectionPin?.capabilities.includes('session:prompt') && <p role="alert">此连接尚未授权发送研究目标，请在连接设置中选择可执行的本人绑定。</p>}
      {notice && <p id={environmentSelectionRejected ? 'research-environment-error' : undefined} className="research-notice" role={environmentSelectionRejected || job?.status === 'failed' ? 'alert' : 'status'}>{notice}</p>}
      {job?.status === 'failed' && <p role="alert">执行任务失败。请核对原请求及任务详情；不能据此认定远端研究已停止。</p>}
      {(pending || session?.state === 'ack_unknown' || session?.state === 'create_ack_unknown') && <aside className="research-decision"><h3>需要核对原请求</h3><p>尚未取得明确回执。请核对原请求；刷新和返回不会重建会话或重新发送目标。</p>{pending && <button disabled={!!busy} onClick={() => void recover()}>核对研究请求</button>}</aside>}
      {session && !sessionWritable && <aside className="research-decision"><h3>继续原研究</h3><p>已有结果和原请求保留。继续时会检查同一连接；若账户授权或目标变化，会停止要求你明确选择。</p><button disabled={!!busy || !!attachment || rebindPending || !ready || !session.nativeSessionId} onClick={() => void continueViewing()}>继续查看研究</button></aside>}
      {!!answers.length && resultPanel}
      {!!visibleSessions.length && <section className="research-session-entry" aria-label="已有研究"><h3>已有研究</h3><p className="quiet">选择原研究查看结果或继续。打开记录不会创建会话或发送目标。</p><div className="personal-session-history">{visibleSessions.map(s => <button key={s.id} aria-pressed={session?.id === s.id} disabled={!!busy || !!pending || !!attachment || rebindPending || !ready} onClick={() => { navigation.current++; localStorage.setItem(selectionStorage, s.id); setSession(s); setSelected(s.connectionRef); }}>{s.observation?.messages.find(m => m.role === 'user')?.events.find(e => e.type === 'text')?.text?.slice(0, 80) || '查看已有研究'}</button>)}</div></section>}
      {managedAvailable && !session && <section className="research-location" aria-label="研究运行位置"><label>运行位置<select aria-label="运行位置" value={location} disabled={!!busy || !!pending || !!attachment || !!environmentRequest} onChange={e => { editEnvironmentSelection(); locationChosen.current = true; setLocation(e.target.value as 'platform' | 'ssh' | 'existing'); }}>{platformAvailable && <option value="platform">平台提供的环境（默认）</option>}{sshAvailable && <option value="ssh">已注册 Linux 服务器（安装研究应用）</option>}<option value="existing">我的已有 OpenResearch 服务</option></select></label><p className="quiet">{location === 'ssh' ? '在已注册服务器上安装研究应用并保留项目数据，无需预装 OpenResearch 服务。使用你自己的默认模型。' : location === 'platform' ? '首次使用自动准备原生 OpenResearch，之后复用同一项目。使用你自己的默认模型。' : '连接你已部署的服务，沿用其模型与原生项目。'}</p>{location === 'ssh' && <><p className="quiet" id="research-ssh-prerequisites">服务器须预装 Linux x86-64、Python 3.12+ 和 Docker，并已有非 root Docker 权限及 SSH 账户。部署维护者须先注册服务器、核对主机公钥并绑定 SSH 授权；当前没有自助注册入口。这里只安装研究应用包，不安装系统依赖。</p><label>我的服务器<select aria-label="我的服务器" value={serverRef} disabled={!!busy || !!environmentRequest} onChange={e => { editEnvironmentSelection(); setServerRef(e.target.value); setServerDirectory(ownedServers.find(server => server.reference === e.target.value)?.defaultDirectory || ''); }}>{ownedServers.map(server => <option key={server.reference} value={server.reference}>{server.name}</option>)}</select></label><label>研究数据目录<input aria-label="研究数据目录" aria-invalid={environmentSelectionRejected} aria-describedby={environmentSelectionRejected ? "research-environment-error research-ssh-prerequisites" : "research-ssh-prerequisites"} value={serverDirectory} disabled={!!busy || !!environmentRequest} onChange={e => { editEnvironmentSelection(); setServerDirectory(e.target.value); }} /></label>{!ownedServers.length && <p role="alert">暂无已授权的本人服务器，请先绑定自己的 SSH 访问身份。</p>}</>}{managedLocation && !modelConfigured && <div className="state-note"><strong>先配置自己的默认模型</strong><p>只需设置一次，平台环境按你的授权调用；模型密钥由平台加密保管。</p>{onModels && <button onClick={onModels}>设置我的模型</button>}</div>}</section>}
      {environmentRequest && <aside className="research-decision"><h3>环境准备请求待核对</h3><p>刷新和返回只恢复环境状态，不会发送研究目标。</p><button disabled={!!busy} onClick={() => void recoverEnvironment()}>核对原环境准备</button><button disabled={!!busy || !!pending || !!session?.activeRequestId} onClick={() => void preparePlatform(false)}>{`明确恢复${environmentLabel}`}</button></aside>}
      <form className="research-composer" onSubmit={e => { e.preventDefault(); begin(); }}>
        <label htmlFor="research-goal">{session ? '继续研究' : '研究目标'}</label><textarea id="research-goal" aria-label="研究目标" placeholder={session ? '想进一步了解什么？' : '描述你想研究的问题，以及希望得到什么结果…'} maxLength={16000} value={researchGoal} disabled={!!busy || !!pending || !!session?.activeRequestId} onChange={e => setResearchGoal(e.target.value)} />
        <details className="research-materials"><summary>补充材料（可选）</summary><label>材料文本或链接<textarea aria-label="补充材料" placeholder="粘贴相关文本或链接；会随目标发送到远端模型。链接不会由 Factory 自动下载。" maxLength={16000} value={materials} disabled={!!busy || !!pending || !!session?.activeRequestId} onChange={e => setMaterials(e.target.value)} /></label></details>
        <div className="research-start-row"><button className="primary" disabled={!ready || !ownerSubmit || !session && managedLocation && managedAvailable && (!modelConfigured || location === 'ssh' && (!serverRef || !serverDirectory.trim())) || !!busy || !!pending || !!attachment || rebindPending || !!session?.activeRequestId || !!session && (!resourceReady && !leaseContinuation || !session.nativeSessionId || session.state === 'create_ack_unknown' || !sessionWritable && !leaseContinuation || !session.connectionPin?.capabilities.includes('session:prompt')) || !researchGoal.trim() || researchText.length > 16000}>{['submit', 'start'].includes(busy) ? '正在提交…' : busy ? '正在核对…' : session ? '继续研究' : '开始研究'}</button><span className="quiet">{!session && managedAvailable && managedLocation ? `${environmentLabel} · 使用我的默认模型` : resourceReady || session ? `使用${project?.name || '已有 OpenResearch 项目'}${session ? ' · 继续原会话' : ' · 自动新建会话'}` : '首次连接配置可在此补齐，目标草稿保留'}</span></div>
        {researchText.length > 16000 && <p role="alert">目标与材料合计超过 16000 字，请缩短后再开始。</p>}
      </form>
      {((needsSetup && (!managedAvailable || location === 'existing')) || setupOpen) && <OpenResearchSetup key={ownerId} ownerId={ownerId} onCreateProject={ref => { setCreationConnection(ref); refreshCreationConnections(n => n + 1); setProjectSetupOpen(true); requestAnimationFrame(() => { projectSetupElement.current?.scrollIntoView({ block: 'start' }); projectSetupElement.current?.querySelector('summary')?.focus(); }); }} onConnected={ref => { navigation.current++; setSelected(ref); setSession(undefined); localStorage.removeItem(selectionStorage); setSetupOpen(false); refresh(n => n + 1); }} />}
      {(!managedAvailable || location === 'existing' || session) && <details ref={projectSetupElement} className="research-project-setup" open={projectSetupOpen} onToggle={e => { setProjectSetupOpen(e.currentTarget.open); if (e.currentTarget.open) refreshCreationConnections(n => n + 1); }}><summary>设置新项目的位置与模型</summary><PersonalOrxProjects ownerId={ownerId} initialConnectionRef={creationConnection} refreshRevision={revision + creationRevision} researchSetup onTask={onTask} onConnected={ref => { navigation.current++; setSelected(ref); setSession(undefined); localStorage.removeItem(selectionStorage); setProjectSetupOpen(false); setSetupOpen(false); refresh(n => n + 1); }} /></details>}
      {!answers.length && resultPanel}
      <details className="research-details"><summary>研究记录与连接设置</summary>
        <button className="secondary" disabled={disabled || !!session?.activeRequestId} onClick={() => setSetupOpen(v => !v)}>设置研究连接</button>
        <label>项目连接<select aria-label="个人会话资源" value={selected} disabled={disabled} onChange={e => { navigation.current++; setSelected(e.target.value); setSession(undefined); localStorage.removeItem(selectionStorage); }}><option value="">选择项目</option>{connections.map(c => <option key={c.ref} value={c.ref}>{connectionNames[c.ref] ?? c.ref}</option>)}</select></label>
        {managedAvailable && <section aria-label="研究环境状态">{environment?.runtimeLimits && <p>研究可调用你的模型，本地研究工具暂不能联网。进行中工作会延长环境租约，单次运行最长 {Math.round(environment.runtimeLimits.maxActiveSeconds / 3600)} 小时。停止或到时若有未完成工作，记录会保留，但暂不能恢复执行；请先请求中断并等待结束。</p>}<p>{environmentLabel}：{environment?.state === 'ready' ? '已就绪' : environment?.state === 'stopped' ? '已停止，原数据保留' : '按开始操作准备或恢复'}</p><button disabled={!!busy || !!pending || !!attachment || !!session?.activeRequestId} onClick={() => void preparePlatform(false)}>{`准备或恢复${environmentLabel}`}</button>{environment?.state === 'ready' && <button disabled={!!busy || !!pending || !!session?.activeRequestId} onClick={() => void act('environment-stop', async () => { const epoch = navigation.current; if (!await ownerIsCurrent(epoch)) return; const result = await applicationEnvironmentApi.stop(ownerId, environment.id, crypto.randomUUID()); if (current(epoch)) { setEnvironment(result.environment); refresh(n => n + 1); setNotice(result.state === 'stopped' ? '平台环境已停止，项目和研究记录保留。恢复环境不会重发目标。' : '停止状态未确认，原数据保留。'); } })}>停止环境并保留数据</button>}</section>}
        {!!nativeSessions.length && <details><summary>已有远端会话</summary>{nativeSessions.map(s => <p key={s.nativeSessionId}>{s.title || '未命名研究'} <button disabled={disabled} onClick={() => void attachNative(s)}>继续此研究</button></p>)}</details>}
        {session && <><details><summary>过程详情与原始输出</summary><p>项目 {session.nativeProjectId} · 会话 {session.nativeSessionId} · 状态 {session.state}</p>{session.observation?.messages.map(m => <article key={m.id}><h4>{m.role === 'assistant' ? '远端代理' : '你的目标'}</h4>{m.events.map((e, i) => e.type === 'text' ? <p key={i} className="research-answer-text">{e.text}</p> : <details key={i}><summary>工具 {e.tool} · {e.status}</summary><pre>{e.output}</pre></details>)}</article>)}</details><PersonalSessionRebind ownerId={ownerId} namespace={namespace} session={session} candidates={connections} disabled={!!busy || !!attachment || !ready} commandPending={!!pending} onPending={rebindChanged} onRebound={next => { navigation.current++; observationGeneration.current++; setSession(next); setSelected(next.connectionRef); refresh(n => n + 1); }} /><button className="secondary" disabled={disabled || !sessionWritable || !session.connectionPin?.capabilities.includes('session:interrupt')} onClick={() => void submit('interrupt')}>请求中断研究</button></>}
        {pending && <p>原请求 {pending.requestId}</p>}{attachment && <p>原会话关联待核对 <button disabled={!!busy} onClick={() => void recoverAttach()}>核对原会话关联</button></p>}
        {job && <p>命令任务 {job.id} · {statusNames[job.status]} {onTask && <button onClick={() => onTask(job.id)}>查看任务详情</button>}</p>}
      </details>
    </section>;
  }
  return <section className="personal-session-workspace" aria-label={`个人 ${engine} 会话`}><h2>{namespace === 'native-openresearch' ? '选择项目与研究会话' : '个人远程会话'}</h2><p>普通模式：连接已有 {engine} 服务，使用它原有的项目与会话。模型密钥留在远程端，无需在 Factory 输入。</p>
    <details className="technical-detail"><summary>模型与执行范围</summary><p>{warning}</p><p>{namespace === 'opencode' ? '这是 OpenCode 原生会话，不是 upstream ORX 项目。' : '这是已有 OpenResearch 项目与原生会话；不是受管单轮文本探测。'}不代表完整科研流程验收或真实端到端兼容性验证。</p></details>
    {notice && <p role="status">{notice}</p>}
    <label>{namespace === 'native-openresearch' ? '我的 OpenResearch 项目' : '个人会话资源'}<select aria-label="个人会话资源" disabled={!ready || researchJourney && !ownerSubmit || !!busy || !!pending || !!attachment || rebindPending} value={selected} onChange={e => { navigation.current++; setSelected(e.target.value); setPlan(undefined); setText(''); }}><option value="">选择已明确绑定的个人资源</option>{connections.map(c => <option key={c.ref} value={c.ref}>{connectionNames[c.ref] ?? `连接 ${c.ref}`}</option>)}</select></label>
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
    {job && <p>Factory 命令任务：{job.id} · {statusNames[job.status] ?? '状态待核对'}。研究进度与回复见上方。{onTask && <button onClick={() => onTask(job.id)}>查看命令任务</button>}</p>}
    <button disabled={!!busy} onClick={() => { navigation.current++; setShowReview(false); setAllowed(false); refresh(n => n + 1); }}>刷新个人资源</button>
    {showReview && plan && <dialog ref={dialog} className="personal-session-dialog" role="dialog" aria-modal="true" aria-label="审阅个人会话命令" onCancel={event => { event.preventDefault(); closeReview(); }}><h3>{action === 'create' ? `创建 ${engine} 会话` : action ? labels[action] : '原个人会话命令'}：确认提交</h3><p>{warning}</p><p>{plan.status === 'ready' ? '命令就绪' : '命令范围尚未通过检查'}</p><CommandSummary plan={plan}/>{plan.missing?.length > 0 && <p>{plan.missing.join('、')}</p>}
      <PlanReviewGate ownerId={ownerId} plan={plan} busy={busy} act={act} onAllowed={setAllowed} />
      <p className="quiet">点击确认，将向上方固定项目或会话提交此命令。</p>
      <div className="button-row"><button className="primary" disabled={!!busy || !allowed || plan.status !== 'ready' || !!pending?.startPlanId} onClick={() => void start()}>确认提交此命令</button><button className="secondary" onClick={closeReview}>关闭审阅</button></div>
    </dialog>}
  </section>;
}
