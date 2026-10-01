import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api.js';
import { PlanReviewGate, PlanReviews } from './PlanReviews.js';
import { MaterialGovernancePanel } from './MaterialGovernance.js';
import { EventTimeline } from './EventTimeline.js';
import {
  materialKey, pendingApproval, pendingQuestion, statusNames, evaluationEvidence,
  type Connection, type FactoryJob, type FactoryMaterial, type FactoryStatus,
  type JobDetail, type Plan, type ExecutionTarget, type User, type DelegationGroup, type DelegationScope,
} from './models.js';

function describe(error: unknown) {
  if (error instanceof ApiError && error.code === 'POLICY_UNSET') return '临时任务审批规则尚未配置，服务端拒绝创建。请联系管理员；预检方案已保留。';
  return error instanceof Error ? error.message : '操作未确认，请重试。';
}
function time(value?: string) {
  if (!value) return '未知';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? '未知' : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
function Badge({ value }: { value: string }) { return <span className={`badge status-${value}`}>{statusNames[value] ?? value}</span>; }
function ErrorMessage({ message, retry }: { message: string; retry?: () => void }) {
  return message ? <div className="error-message" role="alert"><span>{message}</span>{retry && <button className="text-button" onClick={retry}>重新连接</button>}</div> : null;
}
interface ChildDraft { goal: string; mode: 'literature' | 'experiment'; requestId: string }

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [loginMode, setLoginMode] = useState<'demo' | 'live'>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [generation, setGeneration] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    api.status(controller.signal).then(value => setLoginMode(value.mode)).catch(() => { if (!controller.signal.aborted) setLoginMode(undefined); });
    api.session(controller.signal).then(setUser).catch((e: unknown) => {
      if (controller.signal.aborted) return;
      if (e instanceof ApiError && e.status === 401) setUser(null);
      else setError(describe(e));
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [generation]);
  async function login(persona: 'manager' | 'alice' | 'bob') {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try { setUser(await api.login(persona)); } catch (e) { setError(describe(e)); }
    finally { lock.current = false; setBusy(false); }
  }
  async function logout() {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try { await api.logout(); setUser(null); } catch (e) { setError(describe(e)); }
    finally { lock.current = false; setBusy(false); }
  }
  if (user) return <Workspace key={user.id} user={user} logout={() => void logout()} sessionBusy={busy} sessionError={error}/>;
  return <div className="login-page"><div className="login-brand"><span className="brand-symbol" aria-hidden="true">研</span><span>Agent Factory</span></div><section className="login-panel"><p className="quiet">Auto-Research 工作台</p><h1>从研究问题，<br/>到可核对的证据。</h1><p>用已发布的材料组装临时任务。先检查能力与权限，再创建执行实例。</p>{loginMode === 'demo' ? <div className="demo-notice"><strong>本地演示入口</strong><span>确定性运行与合成结果用于验证流程，不代表真实研究已完成。真实模型调用需另行启用。</span></div> : <div className="demo-notice"><strong>{loginMode === 'live' ? '真实运行环境' : '环境状态待确认'}</strong><span>{loginMode === 'live' ? '请使用服务端配置的身份认证入口。演示身份登录已关闭。' : '环境模式尚未确认，演示登录不可用。'}</span></div>}<ErrorMessage message={error} retry={() => setGeneration(n => n + 1)}/>{loginMode === 'demo' && <div className="login-actions">{([['alice', '研究员 Alice'], ['bob', '研究员 Bob'], ['manager', '材料管理员']] as const).map(([id, label]) => <button key={id} className={id === 'alice' ? 'primary' : 'secondary'} disabled={busy || loading} onClick={() => void login(id)}>{label}</button>)}</div>}{loading ? <p role="status" className="quiet">正在检查会话…</p> : !loginMode && <button className="secondary" onClick={() => setGeneration(n => n + 1)}>重新检查环境</button>}<p className="login-footnote">账号权限与任务范围由服务端检查。</p></section></div>;
}

function Workspace({ user, logout, sessionBusy, sessionError }: { user: User; logout: () => void; sessionBusy: boolean; sessionError: string }) {
  const [tab, setTab] = useState<'research' | 'connections' | 'materials' | 'reviews'>('research');
  const [status, setStatus] = useState<FactoryStatus>();
  const [materials, setMaterials] = useState<FactoryMaterial[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [targets, setTargets] = useState<ExecutionTarget[]>([]);
  const [jobs, setJobs] = useState<FactoryJob[]>([]);
  const [selected, setSelected] = useState('');
  const [detail, setDetail] = useState<JobDetail>();
  const [syncError, setSyncError] = useState('');
  const [detailError, setDetailError] = useState('');
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  const [syncedAt, setSyncedAt] = useState('');
  const [refresh, setRefresh] = useState(0);
  const mutationLock = useRef(false);
  const childDrafts = useRef(new Map<string, ChildDraft>());
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const [s, m, c, j, t] = await Promise.all([api.status(controller.signal), api.materials(controller.signal), api.connections(controller.signal), api.jobs(controller.signal), api.executionTargets(controller.signal)]);
        if (controller.signal.aborted) return;
        setStatus(s); setMaterials(m); setConnections(c); setJobs(j); setTargets(t); setSyncError(''); setSyncedAt(new Date().toISOString());
      } catch (e) { if (!controller.signal.aborted) setSyncError(describe(e)); }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 5000);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [refresh]);
  useEffect(() => {
    if (!selected) { setDetail(undefined); return; }
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    setDetail(current => current?.job.id === selected ? current : undefined); setDetailError('');
    async function poll() {
      try {
        const next = await api.detail(selected, controller.signal);
        if (controller.signal.aborted) return;
        setDetail(next); setDetailError('');
      } catch (e) { if (!controller.signal.aborted) setDetailError(describe(e)); }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 2500);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [selected, refresh]);
  const act = useCallback(async (name: string, work: () => Promise<void>) => {
    if (mutationLock.current) return;
    mutationLock.current = true; setBusy(name); setActionError(''); setNotice('');
    try { await work(); setRefresh(n => n + 1); }
    catch (e) { setActionError(describe(e)); }
    finally { mutationLock.current = false; setBusy(''); }
  }, []);
  const retry = () => setRefresh(n => n + 1);
  return <div className="factory-shell"><aside className="sidebar"><div className="brand"><span className="brand-symbol" aria-hidden="true">研</span><div><strong>Agent Factory</strong><small>研究与证据</small></div></div><nav aria-label="工作区"><button aria-current={tab === 'research' ? 'page' : undefined} onClick={() => setTab('research')}><span aria-hidden="true">◈</span>研究工作台</button><button aria-current={tab === 'connections' ? 'page' : undefined} onClick={() => setTab('connections')}><span aria-hidden="true">↗</span>我的资源连接</button>{user.role === 'manager' && <button aria-current={tab === 'materials' ? 'page' : undefined} onClick={() => setTab('materials')}><span aria-hidden="true">▦</span>共享材料管理</button>}</nav>{user.role === 'manager' && <button className="review-nav secondary" aria-current={tab === 'reviews' ? 'page' : undefined} onClick={() => setTab('reviews')}>方案审查</button>}<div className="sidebar-context"><span className="sidebar-line"/><p>能力来自已发布材料。<br/>连接只在授权范围内使用。</p></div><div className="identity"><div className="avatar" aria-hidden="true">{user.name.slice(0, 1)}</div><div><strong>{user.name}</strong><small>{user.role === 'manager' ? '材料管理员' : '研究员'}</small></div><button className="logout" disabled={sessionBusy || !!busy} onClick={logout}>退出</button></div></aside><main className="workspace"><header className="workspace-header"><div><span className="quiet">工作区 / </span><strong>{tab === 'research' ? 'Auto-Research' : tab === 'connections' ? '资源连接' : tab === 'reviews' ? '方案审查' : '共享材料'}</strong></div><div className="sync-state"><span className={`connection-dot ${syncError ? 'disconnected' : ''}`} aria-hidden="true"/>{syncError ? '同步中断' : syncedAt ? '已连接' : '正在连接'}<button className="text-button" onClick={retry} disabled={!!busy}>刷新</button></div></header><div className="workspace-body"><div className="runtime-strip"><div><strong>{status?.mode === 'demo' ? '演示运行' : status?.mode === 'live' ? '真实运行模式' : '运行模式待确认'}</strong><span>{status?.mode === 'demo' ? '本地确定性运行 · 合成结果，不作为研究结论' : status?.mode === 'live' ? '实际执行与证据状态以任务记录为准' : '等待服务端确认，尚未创建任务'}</span></div><span className="integration">{status?.integration ?? '集成状态未知'}</span></div><ErrorMessage message={sessionError}/><ErrorMessage message={syncError} retry={retry}/><ErrorMessage message={actionError}/>{notice && <div className="success-message" role="status">{notice}</div>}{tab === 'research' && <><div className="page-heading"><div><h1>研究工作台</h1><p>描述问题，检查方案，再开始一次有边界的研究。</p></div><div className="worker-metrics"><span><b>{status?.activeWorkers ?? '—'}</b>执行中</span><span><b>{status?.queuedJobs ?? '—'}</b>排队</span><span><b>{status?.maxWorkers ?? '—'}</b>执行上限</span></div></div><div className="research-grid"><div className="research-left"><ResearchComposer busy={busy} act={act} materials={materials} targets={targets} onCreated={id => { setSelected(id); setNotice('创建请求已确认。执行状态以任务记录为准。'); }}/><TaskList jobs={jobs} selected={selected} select={id => { setSelected(id); setActionError(''); }} loading={!syncedAt}/></div><section className="task-panel" aria-label="任务详情">{selected ? detail ? <TaskDetail key={detail.job.id} detail={detail} busy={busy} act={act} onNotice={setNotice} onSelect={id => { setSelected(id); setActionError(''); }} jobs={jobs} drafts={childDrafts.current}/> : <div className="empty-state"><h2>{detailError ? '暂时无法读取任务' : '正在读取任务'}</h2><p>{detailError || '获取执行记录、事件与证据。'}</p><button className="secondary" onClick={retry}>重试</button></div> : <div className="empty-state"><div className="empty-glyph" aria-hidden="true">◎</div><h2>让每一步都有记录</h2><p>创建任务或选择已有任务，在这里查看执行状态、待回答问题与证据产物。</p></div>}{detailError && detail && <ErrorMessage message={`记录更新失败：${detailError}`} retry={retry}/>}</section></div></>}{tab === 'connections' && <Connections connections={connections} loading={!syncedAt}/>} {tab === 'materials' && user.role === 'manager' && <MaterialGovernancePanel user={user} materials={materials} busy={busy} act={act} onNotice={setNotice}/>}{tab === 'reviews' && user.role === 'manager' && <PlanReviews busy={busy} act={act}/>}<footer className="workspace-footer"><span>最近同步 {time(syncedAt)}</span><span>任务执行完成与研究验证通过分别记录</span></footer></div></main></div>;
}

function ResearchComposer({ busy, act, materials, targets, onCreated }: { busy: string; act: (name: string, work: () => Promise<void>) => Promise<void>; materials: FactoryMaterial[]; targets: ExecutionTarget[]; onCreated: (id: string) => void }) {
  const [topic, setTopic] = useState('');
  const [mode, setMode] = useState<'literature' | 'experiment'>('literature');
  const [plan, setPlan] = useState<Plan>();
  const [executionAllowed, setExecutionAllowed] = useState(false);
  const [target, setTarget] = useState('');
  const planRequest = useRef('');
  const instanceRequests = useRef(new Map<string, string>());
  function editTopic(value: string) { setTopic(value); setPlan(undefined); planRequest.current = ''; }
  function editMode(value: 'literature' | 'experiment') { setMode(value); setPlan(undefined); planRequest.current = ''; }
  async function preflight() {
    if (!topic.trim()) return;
    planRequest.current ||= crypto.randomUUID();
    await act('plan', async () => setPlan(await api.plan(topic.trim(), mode, planRequest.current)));
  }
  async function instantiate() {
    if (!plan || plan.status !== 'ready' || !executionAllowed) return;
    const intent = `${plan.id}:${target}`;
    if (!instanceRequests.current.has(intent)) instanceRequests.current.set(intent, crypto.randomUUID());
    await act('instantiate', async () => {
      const job = await api.instantiate(plan.id, instanceRequests.current.get(intent)!, target || undefined);
      onCreated(job.id);
    });
  }
  return <section className="composer" aria-labelledby="composer-title"><div className="section-heading"><h2 id="composer-title">新的研究问题</h2><span className="quiet">临时任务</span></div><form onSubmit={event => { event.preventDefault(); void preflight(); }}><label htmlFor="research-topic">你想研究什么？</label><textarea id="research-topic" rows={4} value={topic} disabled={!!busy} onChange={event => editTopic(event.target.value)} placeholder="例如：比较不同检索策略对小样本问答准确率的影响，并列出可复现实验。" required maxLength={2000}/><fieldset className="mode-options" disabled={!!busy}><legend>研究方式</legend><label className={mode === 'literature' ? 'selected' : ''}><input type="radio" name="mode" checked={mode === 'literature'} onChange={() => editMode('literature')}/>文献与证据</label><label className={mode === 'experiment' ? 'selected' : ''}><input type="radio" name="mode" checked={mode === 'experiment'} onChange={() => editMode('experiment')}/>实验探索</label></fieldset>{targets.length > 0 && <label htmlFor="execution-target">执行位置<select id="execution-target" disabled={!!busy || !!plan} value={target} onChange={event => setTarget(event.target.value)}><option value="">当前 Factory</option>{targets.map(item => <option key={item.id} value={item.id}>{item.name} · 远端 Factory</option>)}</select><small className="quiet">只显示操作员已配置、映射到当前身份的连接。整个任务组在所选位置执行。</small></label>}<button className="primary wide" disabled={!!busy || !topic.trim()} type="submit">{busy === 'plan' ? '正在检查…' : planRequest.current && !plan ? '重试预检' : '生成方案并预检'}</button></form>{plan && <div className="preflight"><div className="section-heading"><h3>执行前检查</h3><span className={`badge ${plan.status === 'ready' ? 'status-ready' : 'status-blocked'}`}>{plan.status === 'ready' ? '预检通过' : '条件未满足'}</span></div><p className="normalized-goal">{plan.normalizedGoal}</p><dl className="plan-details"><dt>所选材料</dt><dd>{plan.materialRefs.length ? plan.materialRefs.map(ref => { const material = materials.find(m => materialKey(m) === materialKey(ref)); return <span className="material-chip" key={materialKey(ref)}>{material?.name ?? ref.id} <small>v{ref.version}</small></span>; }) : '服务端未返回材料'}</dd><dt>能力范围</dt><dd>{plan.capabilities.length ? plan.capabilities.join('、') : '服务端未返回能力范围'}</dd></dl>{plan.missing.length > 0 && <ul className="missing-list">{plan.missing.map((item, i) => <li key={i}>{item}</li>)}</ul>}<p className="policy-note">预检通过不代表已获执行授权。临时任务审批规则由服务端检查，共享材料发布是独立操作。</p><PlanReviewGate key={plan.id} plan={plan} busy={busy} act={act} onAllowed={setExecutionAllowed}/><button className="primary wide" disabled={!!busy || plan.status !== 'ready' || !executionAllowed} onClick={() => void instantiate()}>{busy === 'instantiate' ? '等待创建确认…' : '确认方案并创建任务'}</button><details className="technical-detail"><summary>方案标识</summary><span>方案 {plan.id}</span><span>指纹 {plan.fingerprint}</span><span>预检请求 {planRequest.current}</span>{instanceRequests.current.has(`${plan.id}:${target}`) && <span>创建请求 {instanceRequests.current.get(`${plan.id}:${target}`)}</span>}</details></div>}</section>;
}

function TaskList({ jobs, selected, select, loading }: { jobs: FactoryJob[]; selected: string; select: (id: string) => void; loading: boolean }) {
  return <section className="task-list" aria-labelledby="task-list-title"><div className="section-heading"><h2 id="task-list-title">我的任务</h2><span className="quiet">{jobs.length} 项</span></div>{jobs.length ? <div className="task-list-items">{jobs.map(job => <button className={`task-row ${selected === job.id ? 'selected' : ''}`} key={job.id} onClick={() => select(job.id)} aria-pressed={selected === job.id}><div><strong>{job.input.topic}</strong><small>{time(job.createdAt)} · {job.input.mode === 'experiment' ? '实验探索' : '文献与证据'}</small></div><Badge value={job.status}/></button>)}</div> : <p className="list-empty">{loading ? '正在读取任务…' : '尚无任务。先描述一个研究问题。'}</p>}</section>;
}

function EvaluationEvidence({ detail }: { detail: JobDetail }) {
  const evidence = evaluationEvidence(detail);
  if (!evidence) return <section><h3>评估证据</h3><p className="list-empty">后端尚未提供评估记录。</p></section>;
  const scalar = (key: string) => {
    const value = evidence[key];
    return typeof value === 'string' || (typeof value === 'number' && Number.isFinite(value)) ? String(value) : '未提供';
  };
  const synthetic = evidence.evidenceKind === 'synthetic' || detail.job.runtime === 'demo';
  const suffix = synthetic ? '（合成）' : '（证据类型待核实）';
  const metricNames: Record<string, string> = { inversion_count: '逆序对数量' };
  const directions: Record<string, string> = { lower: '数值越低越好', higher: '数值越高越好' };
  return <section><div className="section-heading"><h3>评估证据</h3><span className="quiet">{synthetic ? '合成评估记录' : scalar('evidenceKind')}</span></div><p className="quiet">以下为后端记录的评估值，不据此认定真实研究改进。</p><dl className="execution-metrics">{([['baseline', '基线值'], ['candidate', '候选值'], ['delta', '差值'], ['elapsedSeconds', '评估耗时（秒）']] as const).map(([key, label]) => <div key={key}><dt>{label}{suffix}</dt><dd>{scalar(key)}</dd></div>)}</dl><dl className="plan-details"><dt>评估指标{suffix}</dt><dd>{metricNames[scalar('metric')] ?? scalar('metric')}</dd><dt>指标方向{suffix}</dt><dd>{directions[scalar('direction')] ?? scalar('direction')}</dd></dl><details className="technical-detail"><summary>评估器与证据来源</summary>{([['evaluatorId', '评估器'], ['evaluatorVersion', '评估器版本'], ['datasetHash', '数据集哈希'], ['outputHash', '输出哈希'], ['runtimeId', '运行环境'], ['modelId', '模型'], ['evidenceKind', '证据类型']] as const).map(([key, label]) => <span key={key}>{label}：{scalar(key)}</span>)}</details></section>;
}

function DelegationPanel({ detail, busy, act, onNotice, onSelect, jobs, drafts }: { detail: JobDetail; busy: string; act: (name: string, work: () => Promise<void>) => Promise<void>; onNotice: (message: string) => void; onSelect: (id: string) => void; jobs: FactoryJob[]; drafts: Map<string, ChildDraft> }) {
  const id = detail.job.id;
  const [draft, setDraft] = useState<ChildDraft>(() => drafts.get(id) ?? { goal: '', mode: 'literature', requestId: '' });
  const rawGroup = detail.snapshot?.delegation;
  const observed = rawGroup && typeof rawGroup === 'object' ? rawGroup as DelegationGroup : undefined;
  const [queried, setQueried] = useState<DelegationGroup>();
  useEffect(() => { setQueried(undefined); }, [rawGroup]);
  const group = queried ?? observed;
  const rawScope = detail.snapshot?.delegationScope;
  const scope = rawScope && typeof rawScope === 'object' ? rawScope as DelegationScope : undefined;
  const canCreate = scope?.allowed === true && detail.job.allowedActions?.includes('delegate') === true && ['queued', 'running', 'waiting_input', 'waiting_approval'].includes(detail.job.status);
  const edit = (changes: Partial<ChildDraft>) => {
    const next = { ...draft, ...changes, requestId: '' };
    setDraft(next); drafts.set(id, next);
  };
  const submit = () => {
    if (!canCreate || draft.goal.trim().length < 2) return;
    const next = { ...draft, requestId: draft.requestId || crypto.randomUUID() };
    setDraft(next); drafts.set(id, next);
    void act('delegate', async () => {
      const receipt = await api.createChild(id, next.goal.trim(), next.mode, next.requestId);
      onNotice(receipt.duplicate ? '已核对原子任务请求；请查看子任务的实际状态。' : '子任务请求已确认；执行状态以服务端记录为准。');
    });
  };
  const count = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value : '未提供';
  function childStatus(child: DelegationGroup['parent']) {
    if (child.unknown) return '状态待核对';
    if (child.failed) return `执行或权限检查失败 · ${child.stopped ? '已确认停止' : '停止尚未确认'}`;
    const native: Record<string, string> = { pending: '排队中', paused: '等待继续', cancelled: '已取消', error: '执行失败' };
    const status = statusNames[child.nativeStatus ?? ''] ?? native[child.nativeStatus ?? ''] ?? '状态未提供';
    return `${status} · ${child.stopped ? '已确认停止' : '停止尚未确认'}`;
  }
  return <section className="delegation-panel"><div className="section-heading"><h3>任务委托</h3><button className="text-button" disabled={!!busy} onClick={() => void act('group', async () => { setQueried(await api.group(id)); onNotice('已读取任务组的实际状态。'); })}>核对任务组</button></div><p className="quiet">子任务受父任务与根任务的不可变权限约束，共享工具预算。取消当前任务会向其后代发出取消请求，全部停止仍需确认。</p>{scope ? <><div className="delegation-budget"><span>共享工具调用 <b>{count(scope.sharedBudget?.toolCallsUsed)} / {count(scope.sharedBudget?.toolCallsLimit)}</b></span><span>累计子任务 <b>{count(scope.sharedBudget?.childrenUsed)} / {count(scope.sharedBudget?.childrenLimit)}</b></span><span>当前深度 <b>{count(scope.depth)} / {count(scope.sharedBudget?.maxDepth)}</b></span></div><details className="technical-detail"><summary>不可变范围与共享预算</summary><span>父任务：{scope.parentTaskId ?? '未提供'}</span><span>根任务：{scope.rootTaskId ?? '未提供'}</span><span>能力范围：{scope.capabilities?.join('、') || '未提供'}</span><span>工具范围：{scope.tools?.join('、') || '未提供'}</span><pre>{JSON.stringify(scope.budget ?? {}, null, 2)}</pre>{draft.requestId && <span>创建请求：{draft.requestId}</span>}</details></> : <p className="quiet">后端尚未提供委托权限与共享预算，暂不能创建子任务。</p>}{group ? <><p className="delegation-state">{group.unknown ? '任务组存在未确认状态' : group.allStopped ? '任务组已确认全部停止' : group.pending ? '仍有子任务待完成或停止确认' : '父任务停止结果仍待确认'}</p>{group.children?.length ? <ul className="delegation-children">{group.children.map((child, i) => <li key={child.taskId ?? child.link?.request_id ?? i}><div><strong>{jobs.find(job => job.id === child.taskId)?.input.topic ?? '已登记的子任务'}</strong><small>{childStatus(child)}{child.link?.depth !== undefined ? ` · 深度 ${child.link.depth}` : ''}</small></div><button className="secondary" disabled={!!busy || !child.taskId} onClick={() => child.taskId && onSelect(child.taskId)}>查看子任务</button></li>)}</ul> : <p className="quiet">当前没有后代任务记录。</p>}</> : <p className="quiet">任务组状态尚未提供。</p>}<form className="delegation-form" onSubmit={event => { event.preventDefault(); submit(); }}><label htmlFor="child-goal">子任务目标</label><textarea id="child-goal" rows={2} maxLength={2000} value={draft.goal} disabled={!!busy || !canCreate} onChange={event => edit({ goal: event.target.value })} placeholder="将当前目标拆分为一个有边界的子任务"/><div className="delegation-form-actions"><label>执行方式<select value={draft.mode} disabled={!!busy || !canCreate} onChange={event => edit({ mode: event.target.value as ChildDraft['mode'] })}><option value="literature">文献与证据</option><option value="experiment">实验探索</option></select></label><button className="primary" disabled={!!busy || !canCreate || draft.goal.trim().length < 2}>{busy === 'delegate' ? '等待创建确认…' : draft.requestId ? '核对原创建请求' : '确认创建子任务'}</button></div></form><p className="quiet">通常每人最多 2 个活跃任务，父任务会占用一个名额；累计子任务与深度限制由服务端检查。{!canCreate && scope && '当前任务没有可用的委托授权。'}</p></section>;
}

function TaskDetail({ detail, busy, act, onNotice, onSelect, jobs, drafts }: { detail: JobDetail; busy: string; act: (name: string, work: () => Promise<void>) => Promise<void>; onNotice: (message: string) => void; onSelect: (id: string) => void; jobs: FactoryJob[]; drafts: Map<string, ChildDraft> }) {
  const { job, events, artifacts } = detail;
  const [answer, setAnswer] = useState('');
  const question = pendingQuestion(detail);
  const approval = pendingApproval(detail);
  useEffect(() => { setAnswer(''); }, [question?.id, question?.version]);
  const allowed = (action: string) => job.allowedActions?.includes(action) === true;
  const terminal = ['canceled', 'completed', 'failed'].includes(job.status);
  const mutate = (name: string, work: () => Promise<FactoryJob>, notice: string) => void act(name, async () => { await work(); onNotice(notice); });
  const metrics = detail.snapshot?.metrics;
  const metricEntries = metrics && typeof metrics === 'object' ? Object.entries(metrics as Record<string, unknown>).filter(([key, value]) => /^(tokens|inputTokens|outputTokens|elapsedSeconds|steps|durationMs|attempts|workerSeconds)$/.test(key) && (typeof value === 'number' || typeof value === 'string')) : [];
  return <><div className="task-title"><div className="section-heading"><span className="quiet">任务记录</span><Badge value={job.status}/></div><h2>{job.input.topic}</h2><p>{job.runtime === 'demo' ? '确定性演示 · 结果为合成数据' : '真实运行 · 证据需要单独验证'}</p>{job.executionPlacement && <p className="remote-placement">执行位置：{job.executionPlacement.targetRef} · {job.executionPlacement.kind === 'remote-factory' ? '远端 Factory' : job.executionPlacement.kind}。执行结果与停止确认以接收端记录为准。</p>}<div className="task-facts"><span>创建 {time(job.createdAt)}</span><span>尝试 {job.attempt ?? '未知'}</span><span>验证 {job.validationStatus ?? '未提供'}</span></div></div><div className="task-controls">{!terminal && <button className="secondary danger" disabled={!!busy || !allowed('cancel') || job.status === 'canceling'} onClick={() => mutate('cancel', () => api.cancel(job.id), '取消请求已确认；等待服务端报告任务状态。')}>{job.status === 'canceling' ? '等待取消结果' : '请求取消'}</button>}<button className="secondary" disabled={!!busy || !allowed('reconcile')} onClick={() => mutate('reconcile', () => api.reconcile(job.id), '已请求核对状态，以新的任务记录为准。')}>核对执行状态</button>{!job.allowedActions && <span className="quiet">可用操作待服务端确认</span>}</div>{job.error && <ErrorMessage message={job.error}/>} {job.status === 'canceling' && <div className="state-note">服务端已接受取消请求，不代表执行已经停止。状态更新后才能确认释放结果。</div>}{job.status === 'completed' && <div className="state-note">执行已完成。研究结论是否通过验证：{job.validationStatus ?? '后端尚未提供验证结论'}。</div>}{job.status === 'waiting_input' && <section className="attention-panel"><h3>需要你的回答</h3><p>{question?.text ?? job.question ?? '问题内容尚未提供。'}</p>{question ? <form onSubmit={event => { event.preventDefault(); mutate('answer', () => api.answer(job.id, question.id, question.version, answer.trim()), '回答已提交，等待服务端继续执行。'); }}><label htmlFor="job-answer">回答</label><textarea id="job-answer" value={answer} onChange={event => setAnswer(event.target.value)} rows={3} disabled={!!busy}/><button className="primary" disabled={!!busy || !allowed('answer') || !answer.trim()}>提交回答</button></form> : <p className="quiet">缺少问题标识或版本，暂不能安全提交。</p>}</section>}{job.status === 'waiting_approval' && <section className="attention-panel"><h3>等待执行审批</h3><p>{approval?.scope ?? job.approval?.scope ?? '审批范围尚未提供。'}</p><p className="quiet">此决定只针对本次执行，不会发布共享材料。</p>{approval ? <div className="button-row"><button className="primary" disabled={!!busy || !allowed('approve')} onClick={() => mutate('approve', () => api.approve(job.id, approval.id, approval.version, true), '审批决定已提交，等待服务端处理。')}>同意本次请求</button><button className="secondary" disabled={!!busy || !allowed('approve')} onClick={() => mutate('approve', () => api.approve(job.id, approval.id, approval.version, false), '拒绝决定已提交，等待服务端处理。')}>拒绝</button></div> : <p className="quiet">缺少审批标识或版本，暂不能安全提交。</p>}</section>}<div className="detail-sections"><DelegationPanel detail={detail} busy={busy} act={act} onNotice={onNotice} onSelect={onSelect} jobs={jobs} drafts={drafts}/><EventTimeline key={job.id} jobId={job.id} latest={events}/><section><div className="section-heading"><h3>证据与产物</h3><span className="quiet">{job.evidenceKind ?? '证据类型未提供'}</span></div>{artifacts.length ? <ul className="artifact-list">{artifacts.map(artifact => <li key={artifact.id}><a href={api.artifactUrl(job.id, artifact.id)} target="_blank" rel="noreferrer"><span className="file-glyph" aria-hidden="true">▤</span><div><strong>{artifact.name}</strong><small>{artifact.mediaType} · {artifact.size.toLocaleString()} 字节</small></div><span>查看</span></a><details className="technical-detail"><summary>完整性与记录时间</summary><span>SHA-256 {artifact.sha256}</span><span>记录于 {time(artifact.createdAt)}</span></details></li>)}</ul> : <p className="list-empty">尚无产物。执行完成也不自动代表已有有效研究证据。</p>}</section><EvaluationEvidence detail={detail}/><section><h3>执行指标</h3>{metricEntries.length ? <dl className="execution-metrics">{metricEntries.map(([key, value]) => <div key={key}><dt>{({ tokens: '令牌总数', inputTokens: '输入令牌', outputTokens: '输出令牌', elapsedSeconds: '耗时（秒）', steps: '执行步骤', durationMs: '耗时（毫秒）', attempts: '尝试次数', workerSeconds: '工作耗时（秒）' } as Record<string, string>)[key] ?? key}{job.runtime === 'demo' ? '（合成）' : ''}</dt><dd>{String(value)}</dd></div>)}</dl> : <p className="list-empty">后端尚未提供指标；不估算耗时、费用或进度。</p>}</section><details className="technical-detail"><summary>任务引用</summary><span>任务 {job.id}</span><span>方案 {job.planId ?? '未提供'}</span><span>定义 {job.definitionId} v{job.definitionVersion}</span></details></div></>;
}

function Connections({ connections, loading }: { connections: Connection[]; loading: boolean }) {
  return <section className="connections-page"><div className="page-heading"><div><h1>我的资源连接</h1><p>查看授权范围内的资源引用。运行与计算资源可位于远端。</p></div></div><div className="state-note">这里仅显示服务端返回的连接摘要，不显示密钥，也不允许扩大访问范围。远程服务是否可用须由后端实际检查。</div>{connections.length ? <div className="connection-table"><div className="table-heading"><span>资源</span><span>提供方</span><span>连接状态</span></div>{connections.map(connection => <div className="connection-record" key={connection.id}><div><strong>{connection.name}</strong><small>引用 {connection.id}</small></div><span>{connection.providerId}</span><span className={`badge ${connection.status === 'configured' ? 'status-ready' : 'status-blocked'}`}>{connection.status === 'configured' ? '已配置 · 可达性未确认' : '不可用'}</span></div>)}</div> : <div className="empty-state"><h2>{loading ? '正在读取连接' : '暂无可用连接摘要'}</h2><p>请由管理员配置授权连接；本页不创建凭据或远端资源。</p></div>}</section>;
}
