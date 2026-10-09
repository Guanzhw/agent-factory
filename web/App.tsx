import { ModelSettings } from './ModelSettings.js';
import { FeeVisibility } from './FeeVisibility.js';
import { OpenResearchWorkspace } from './OpenResearchWorkspace.js';
import { readWorkspaceRoute, sameWorkspaceRoute, workspaceTabs, workspaceUrl, type WorkspaceRoute, type WorkspaceTab } from './workspaceNavigation.js';
import { WorkflowPanel } from './WorkflowPanel.js';
import { AutoResearch } from './AutoResearch.js';
import { ComparisonPanel, ComparisonReport, type ComparisonSeed } from './ComparisonPanel.js';
import { SchedulesPanel } from './SchedulesPanel.js';
import { ScheduleDiagnostics } from './ScheduleDiagnostics.js';
import { SynthesisJourney } from './SynthesisJourney.js';
import { SynthesisReport } from './SynthesisReport.js';
import type { SynthesisSnapshot } from './synthesisJourneyState.js';
import { browserAuthConfig, clearBrowserSession, consumeSigninFailure, startBrowserLogin, subscribeSessionExpiry, type BrowserAuthConfig } from './browserAuth.js';
import { ApprovedRecoveryPanel, approvedRecovery } from './ApprovedRecovery.js';
import { StoragePanel } from './StoragePanel.js';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api.js';
import { ControlRecovery, commandNotice } from './ControlRecovery.js';
import { persistCommandPointer, type ControlIntent } from './controlCommandStorage.js';
import { PlanReviews } from './PlanReviews.js';
import { MaterialGovernancePanel } from './MaterialGovernance.js';
import { EventTimeline } from './EventTimeline.js';
import { delegationModes, delegationModeName } from './delegationModes.js';
import { RemoteHandoffPanel } from './RemoteHandoff.js';
import { nativeInteractionAvailable, remoteHandoffState } from './remoteHandoffState.js';
import { ApplicationComposer } from './ApplicationComposer.js';
import { ConnectionsPanel } from './ConnectionsPanel.js';
import { ApplicationGovernance } from './ApplicationGovernance.js';
import { NativeCommandResult } from './NativeCommandResult.js';
import { ArtifactDownload } from './VerifiedArtifactDownload.js';
import { LiteratureEvidencePanel } from './LiteratureEvidence.js';
import { UsageLedgerPanel } from './UsageLedger.js';
import { OrxExperimentPanel } from './OrxExperiment.js';
import { orxExperimentState } from './orxExperimentState.js';
import {
  pendingApproval, pendingQuestion, statusNames, evaluationEvidence,
  type FactoryJob, type FactoryMaterial, type FactoryStatus,
  type JobDetail, type ExecutionTarget, type User, type DelegationGroup, type DelegationScope,
} from './models.js';

function describe(error: unknown) {
  if (error instanceof ApiError && error.code === 'OFFLINE') return '无法连接服务。已保留上次读取的记录；请恢复网络后重新连接，未确认的操作须核对原请求。';
  if (error instanceof ApiError && error.code === 'POLICY_UNSET') return '临时任务审批规则尚未配置，服务端拒绝创建。请联系管理员；预检方案已保留。';
  return error instanceof Error ? error.message : '操作未确认，请重试。';
}
function time(value?: string) {
  if (!value) return '未知';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? '未知' : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
function Badge({ value, label }: { value: string; label?: string }) { return <span className={`badge status-${value}`}>{label ?? statusNames[value] ?? value}</span>; }
function ErrorMessage({ message, retry }: { message: string; retry?: () => void }) {
  return message ? <div className="error-message" role="alert"><span>{message}</span>{retry && <button className="text-button" onClick={retry}>重新连接</button>}</div> : null;
}
interface ChildDraft { goal: string; mode: string; requestId: string }

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const currentUser = useRef<User | null>(null);
  currentUser.current = user;
  const [loading, setLoading] = useState(true);
  const [authConfig, setAuthConfig] = useState<BrowserAuthConfig>();
  const [loginMode, setLoginMode] = useState<'demo' | 'live'>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [generation, setGeneration] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setAuthConfig(undefined); setUser(null);
    const failed = consumeSigninFailure(window.location, url => window.history.replaceState(null, '', url));
    if (failed) setError('登录未完成或验证失败，请重新开始登录。');
    async function load() {
      try {
        const config = await browserAuthConfig(controller.signal);
        if (controller.signal.aborted) return;
        setAuthConfig(config);
        if (config.enabled) setLoginMode(config.developmentOnly ? 'demo' : 'live');
        else {
          const status = await api.status(controller.signal);
          if (controller.signal.aborted) return;
          setLoginMode(status.mode);
        }
        const current = await api.session(controller.signal);
        if (!controller.signal.aborted) { setUser(current); setError(''); }
      } catch (e) {
        if (controller.signal.aborted || e instanceof Error && e.name === 'AbortError') return;
        if (!(e instanceof ApiError && e.status === 401)) setError(describe(e));
      } finally { if (!controller.signal.aborted) setLoading(false); }
    }
    void load();
    return () => controller.abort();
  }, [generation]);
  useEffect(() => subscribeSessionExpiry(() => {
    setUser(null); setBusy(false); lock.current = false;
    if (currentUser.current) setError('登录会话已过期，请重新登录。未确认的操作请在登录后核对记录。');
  }), []);
  async function ssoLogin() {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try { window.location.assign(await startBrowserLogin()); }
    catch { setError('登录暂时不可用，请重新开始登录。'); lock.current = false; setBusy(false); }
  }
  async function login(persona: 'manager' | 'alice' | 'bob') {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try { setUser(await api.login(persona)); } catch (e) { setError(describe(e)); }
    finally { lock.current = false; setBusy(false); }
  }
  async function logout() {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try { await api.logout(); clearBrowserSession(); setUser(null); } catch (e) { setError(describe(e)); }
    finally { lock.current = false; setBusy(false); }
  }
  if (user && authConfig) return <Workspace key={user.id} user={user} logout={() => void logout()} sessionBusy={busy} sessionError={error}/>;
  return <div className="login-page"><div className="login-brand"><span className="brand-symbol" aria-hidden="true">研</span><span>Agent Factory</span></div><section className="login-panel"><p className="quiet">Auto-Research 工作台</p><h1>从研究问题，<br/>到可核对的证据。</h1><p>选择应用，描述研究目标后开始。进度与结果都在任务记录中。</p>{loginMode === 'demo' ? <div className="demo-notice"><strong>{authConfig?.developmentOnly ? '开发模拟登录（仅本地）' : '本地演示入口'}</strong><span>确定性运行与合成结果用于验证流程，不代表真实研究已完成。真实模型调用需另行启用。</span></div> : <div className="demo-notice"><strong>{loginMode === 'live' ? '真实运行环境' : '环境状态待确认'}</strong><span>{loginMode === 'live' ? authConfig?.enabled ? '使用组织的统一身份认证登录，账号权限由服务端核对。' : '请使用服务端配置的身份认证入口。演示身份登录已关闭。' : '环境模式尚未确认，演示登录不可用。'}</span></div>}<ErrorMessage message={error} retry={() => setGeneration(n => n + 1)}/>{authConfig?.enabled && <div className="login-actions"><button className="primary" disabled={busy || loading} onClick={() => void ssoLogin()}>{busy ? '正在前往登录…' : authConfig.developmentOnly ? '选择开发测试身份' : '使用企业账号登录'}</button></div>}{authConfig?.enabled === false && loginMode === 'demo' && <div className="login-actions">{([['alice', '研究员 Alice'], ['bob', '研究员 Bob'], ['manager', '材料管理员']] as const).map(([id, label]) => <button key={id} className={id === 'alice' ? 'primary' : 'secondary'} disabled={busy || loading} onClick={() => void login(id)}>{label}</button>)}</div>}{loading ? <p role="status" className="quiet">正在检查会话…</p> : (!authConfig || !loginMode) && <button className="secondary" onClick={() => setGeneration(n => n + 1)}>重新检查环境</button>}<p className="login-footnote">账号权限与任务范围由服务端检查。</p></section></div>;
}

export function Workspace({ user, logout, sessionBusy, sessionError }: { user: User; logout: () => void; sessionBusy: boolean; sessionError: string }) {
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [route, setRoute] = useState(() => readWorkspaceRoute(new URL(window.location.href), user.role === 'manager'));
  const routeRef = useRef(route);
  const navigate = (patch: Partial<WorkspaceRoute>) => {
    const next = { ...routeRef.current, ...patch };
    if (sameWorkspaceRoute(next, routeRef.current)) return;
    window.history.pushState(null, '', workspaceUrl(new URL(window.location.href), next));
    routeRef.current = next; setRoute(next);
  };
  const tab = route.tab;
  const selected = route.task;
  const setTab = (tab: WorkspaceTab) => navigate({ tab });
  const setSelected = (task: string) => navigate({ tab: 'research', task });
  useEffect(() => {
    const restore = () => {
      const next = readWorkspaceRoute(new URL(window.location.href), user.role === 'manager');
      routeRef.current = next; setRoute(next);
    };
    // Normalize unknown/unauthorized views without adding a history entry.
    window.history.replaceState(null, '', workspaceUrl(new URL(window.location.href), routeRef.current));
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, [user.role]);
  const [status, setStatus] = useState<FactoryStatus>();
  const [materials, setMaterials] = useState<FactoryMaterial[]>([]);
  const [targets, setTargets] = useState<ExecutionTarget[]>([]);
  const [jobs, setJobs] = useState<FactoryJob[]>([]);
  const [scheduleSeed, setScheduleSeed] = useState<{ planId: string; planFingerprint: string; goal: string }>();
  const [sourceSeed, setSourceSeed] = useState<SynthesisSnapshot>();
  const [comparisonSeed, setComparisonSeed] = useState<ComparisonSeed>();
  const [detail, setDetail] = useState<JobDetail>();
  const [syncError, setSyncError] = useState('');
  const [detailError, setDetailError] = useState('');
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  const [syncedAt, setSyncedAt] = useState('');
  const [refresh, setRefresh] = useState(0);
  const taskPanel = useRef<HTMLElement>(null);
  useEffect(() => { if (selected && tab === 'research') taskPanel.current?.focus(); }, [selected, tab]);
  const mutationLock = useRef(false);
  const childDrafts = useRef(new Map<string, ChildDraft>());
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const [s, m, j, t] = await Promise.all([api.status(controller.signal), api.materials(controller.signal), api.jobs(controller.signal), api.executionTargets(controller.signal)]);
        if (controller.signal.aborted) return;
        setStatus(s); setMaterials(m); setJobs(j); setTargets(t); setSyncError(''); setSyncedAt(new Date().toISOString());
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
  return <FeeVisibility enabled={status?.feeManagementEnabled === true}><div className="factory-shell"><aside className="sidebar"><div className="brand"><span className="brand-symbol" aria-hidden="true">研</span><div><strong>Agent Factory</strong><small>研究与证据</small></div></div><nav aria-label="工作区"><span className="nav-group-label">开始与查看</span>{(['catalog', 'openresearch', 'research', 'models'] as const).map(value => <button key={value} aria-current={tab === value ? 'page' : undefined} onClick={() => setTab(value)}>{workspaceTabs[value]}</button>)}<button className="mobile-nav-toggle" aria-expanded={navigationOpen} aria-controls="secondary-navigation" onClick={() => setNavigationOpen(value => !value)}>{navigationOpen ? '收起工具与管理入口' : '工具、资源与管理入口'}</button><div id="secondary-navigation" className={`secondary-navigation ${navigationOpen ? 'expanded' : ''}`}><span className="nav-group-label">工具与资源</span>{(['connections', 'comparison', 'schedules', 'storage'] as const).map(value => <button key={value} aria-current={tab === value ? 'page' : undefined} onClick={() => setTab(value)}>{workspaceTabs[value]}</button>)}<span className="nav-group-label">高级</span><button aria-current={tab === 'developer' ? 'page' : undefined} onClick={() => setTab('developer')}>开发者装配</button>{user.role === 'manager' && <><span className="nav-group-label">管理员</span>{(['applications', 'materials', 'reviews'] as const).map(value => <button key={value} aria-current={tab === value ? 'page' : undefined} onClick={() => setTab(value)}>{workspaceTabs[value]}</button>)}</>}</div></nav><div className="sidebar-context"><span className="sidebar-line"/><p>能力来自已发布材料。<br/>连接只在授权范围内使用。</p></div><div className="identity"><div className="avatar" aria-hidden="true">{user.name.slice(0, 1)}</div><div><strong>{user.name}</strong><small>{user.role === 'manager' ? '材料管理员' : '研究员'}</small></div><button className="logout" disabled={sessionBusy || !!busy} onClick={logout}>退出</button></div></aside><main className="workspace"><header className="workspace-header"><div><span className="quiet">工作区 / </span><strong>{workspaceTabs[tab]}</strong></div><div className="sync-state"><span className={`connection-dot ${syncError ? 'disconnected' : ''}`} aria-hidden="true"/>{syncError ? '同步中断' : syncedAt ? '已连接' : '正在连接'}<button className="text-button" onClick={retry} disabled={!!busy}>刷新</button></div></header><div className="workspace-body"><div className="runtime-strip"><div><strong>{status?.mode === 'demo' ? '演示运行' : status?.mode === 'live' ? '真实运行模式' : '运行模式待确认'}</strong><span>{status?.mode === 'demo' ? '开发验证环境 · 实际模型与证据状态以任务记录为准' : status?.mode === 'live' ? '实际执行与证据状态以任务记录为准' : '等待服务端确认，尚未创建任务'}</span></div><span className="integration">{status?.integration ?? '集成状态未知'}</span></div><ErrorMessage message={sessionError}/><ErrorMessage message={syncError} retry={retry}/><ErrorMessage message={actionError}/>{notice && <div className="success-message" role="status">{notice}</div>}{tab === 'catalog' && <section><div className="page-heading"><div><p className="quiet">FACTORY / 应用目录</p><h1>选择你的工作区</h1><p>Factory 管理权限、资源与执行；应用管理自己的项目和研究过程。</p></div></div><div className="or-catalog-grid"><article className="or-catalog-card"><span className="quiet">研究应用</span><h2>OpenResearch</h2><p>关联原生项目、整理研究会话，沿原任务查看结果与证据。</p><p className="quiet">可用能力以工作区服务端检查为准。</p><button className="primary" onClick={() => setTab('openresearch')}>进入 OpenResearch</button></article><article className="or-catalog-card"><span className="quiet">个人设置</span><h2>我的模型/API</h2><p>为 Agno 原生任务保存自己的模型与密钥。OpenResearch 远程会话使用其服务自身的设置。</p><button className="secondary" onClick={() => setTab('models')}>设置我的模型/API</button></article></div></section>}{tab === 'models' && <ModelSettings ownerId={user.id} onResearch={() => setTab('catalog')}/>} {tab === 'openresearch' && <OpenResearchWorkspace key={user.id} ownerId={user.id} selectedProject={route.project ?? ''} selectedMode={route.mode ?? (route.project ? 'managed' : 'personal')} onMode={mode => navigate({ tab: 'openresearch', mode })} onProject={project => navigate({ project, mode: 'managed' })} onTask={setSelected} onResources={() => setTab('connections')} onCatalog={() => setTab('catalog')}/>}{tab === 'developer' && <section><div className="page-heading"><div><h1>开发者装配</h1><p>高级材料与应用契约验证。Checksum 仅为开发示例。</p></div></div><ApplicationComposer key={comparisonSeed ? `${comparisonSeed.applicationRef.sha256}:${comparisonSeed.mode}` : sourceSeed?.id ?? 'ordinary'} comparisonSeed={comparisonSeed} sourceSeed={sourceSeed} onSchedule={plan => { setScheduleSeed({ planId: plan.id, planFingerprint: plan.fingerprint, goal: plan.normalizedGoal }); setTab('schedules'); }} user={user} busy={busy} act={act} materials={materials} targets={targets} onCreated={id => { setSelected(id); setNotice('创建请求已确认。请在任务记录中查看进度与结果。'); }}/><details className="technical-detail"><summary>受控实验开发入口</summary><p>预设工作负载与原生 OpenResearch 项目彼此独立。</p><button className="secondary" onClick={() => setTab('autoresearch')}>打开受控 Auto-Research 实验</button></details></section>}{tab === 'autoresearch' && <AutoResearch key={`${user.id}:${route.run || 'entry'}`} ownerId={user.id} api={api.autoresearch} runId={route.run || undefined} onRun={(run, passive) => { if (!passive) navigate({ tab: 'autoresearch', run }); }} onOpenTasks={() => setTab('catalog')}/>} {tab === 'research' && <><ControlRecovery ownerId={user.id} onSelect={setSelected} busy={busy} act={act}/><div className="page-heading"><div><h1>任务与证据</h1><p>查看原任务、审批、执行进度与证据。返回 OpenResearch 继续项目研究。</p></div><div className="worker-metrics"><span><b>{status?.activeWorkers ?? '—'}</b>执行中</span><span><b>{status?.queuedJobs ?? '—'}</b>排队</span><span><b>{status?.maxWorkers ?? '—'}</b>执行上限</span></div></div><div className={`research-grid ${selected ? 'has-task' : 'new-task-layout'}`}><div className="research-left"><TaskList jobs={jobs} selected={selected} select={id => { setSelected(id); setActionError(''); }} loading={!syncedAt}/></div><section className="task-panel" aria-label="任务详情" id="task-detail" ref={taskPanel} tabIndex={-1}>{selected ? detail?.job.id === selected ? <TaskDetail key={detail.job.id} detail={detail} busy={busy} act={act} onNotice={setNotice} onSelect={id => { setSelected(id); setActionError(''); }} jobs={jobs} drafts={childDrafts.current} ownerId={user.id} onSourceSnapshot={snapshot => { setComparisonSeed(undefined); setSourceSeed(snapshot); setTab('developer'); setNotice('来源已固定到装配输入，请检查应用与本人连接，再生成方案。'); document.getElementById('composer-title')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }}/> : <div className="empty-state"><h2>{detailError ? '暂时无法读取任务' : '正在读取任务'}</h2><p>{detailError || '获取执行记录、事件与证据。'}</p><button className="secondary" onClick={retry}>重试</button></div> : <div className="empty-state"><div className="empty-glyph" aria-hidden="true">◎</div><h2>让每一步都有记录</h2><p>创建任务或选择已有任务，在这里查看执行状态、待回答问题与证据产物。</p></div>}{detailError && detail && <ErrorMessage message={`记录更新失败：${detailError}`} retry={retry}/>}</section></div></>}{tab === 'comparison' && <ComparisonPanel ownerId={user.id} api={api.comparisons} disabled={!!busy} onPrepare={seed => { setSourceSeed(undefined); setComparisonSeed(seed); setTab('developer'); setNotice('比较输入已固定，请生成提案并完成独立方案审查。'); }}/>} {tab === 'schedules' && <><ScheduleDiagnostics key={`diagnostics:${user.id}`} ownerId={user.id} api={api.scheduleDiagnostics}/><SchedulesPanel key={user.id} ownerId={user.id} canManage={user.role === 'manager'} seed={scheduleSeed} api={api.schedules} disabled={!!busy} onTask={id => { setSelected(id); setTab('research'); }}/></>} {tab === 'storage' && <StoragePanel key={user.id} ownerId={user.id} busy={busy} act={act} onNotice={setNotice}/>} {tab === 'connections' && <ConnectionsPanel user={user} jobs={jobs} busy={busy} act={act} onNotice={setNotice} onTask={id => { setSelected(id); setTab('research'); }}/>} {tab === 'materials' && user.role === 'manager' && <MaterialGovernancePanel user={user} materials={materials} busy={busy} act={act} onNotice={setNotice}/>}{tab === 'applications' && user.role === 'manager' && <ApplicationGovernance user={user} materials={materials} busy={busy} act={act} onNotice={setNotice}/>}{tab === 'reviews' && user.role === 'manager' && <PlanReviews ownerId={user.id} busy={busy} act={act}/>}<footer className="workspace-footer"><span>最近同步 {time(syncedAt)}</span><span>任务执行完成与研究验证通过分别记录</span></footer></div></main></div></FeeVisibility>;
}

function TaskList({ jobs, selected, select, loading }: { jobs: FactoryJob[]; selected: string; select: (id: string) => void; loading: boolean }) {
  return <section className="task-list" aria-labelledby="task-list-title"><div className="section-heading"><h2 id="task-list-title">我的任务</h2><span className="quiet">{jobs.length} 项</span></div>{jobs.length ? <div className="task-list-items">{jobs.map(job => <button className={`task-row ${selected === job.id ? 'selected' : ''}`} key={job.id} onClick={() => select(job.id)} aria-pressed={selected === job.id}><div><strong>{job.input.topic}</strong><small>{time(job.createdAt)} · {delegationModeName(job.input.mode)}</small></div><Badge value={job.status} label={job.status === 'waiting_approval' && job.executionPlacement?.state === 'PREPARING' ? '等待接收端审查' : undefined}/></button>)}</div> : <p className="list-empty">{loading ? '正在读取任务…' : '尚无任务。在 OpenResearch 中选择自己的项目与会话，提交研究目标后在此查看进度与结果。'}</p>}</section>;
}

function EvaluationEvidence({ detail }: { detail: JobDetail }) {
  const evidence = evaluationEvidence(detail);
  if (!evidence) return <section><h3>评估证据</h3><p className="list-empty">后端尚未提供评估记录。</p></section>;
  const scalar = (key: string) => {
    const value = evidence[key];
    return typeof value === 'string' || (typeof value === 'number' && Number.isFinite(value)) ? String(value) : '未提供';
  };
  const synthetic = evidence.evidenceKind === 'synthetic';
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
  const modeChoices = delegationModes(scope, draft.mode, !!draft.requestId);
  const canCreate = modeChoices.available && scope?.allowed === true && detail.job.allowedActions?.includes('delegate') === true && ['queued', 'running', 'waiting_input', 'waiting_approval'].includes(detail.job.status);
  const edit = (changes: Partial<ChildDraft>) => {
    const next = { ...draft, ...changes, requestId: '' };
    setDraft(next); drafts.set(id, next);
  };
  const submit = () => {
    if (!canCreate || draft.goal.trim().length < 2) return;
    const next = { ...draft, mode: modeChoices.selected, requestId: draft.requestId || crypto.randomUUID() };
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
  return <section className="delegation-panel"><div className="section-heading"><h3>任务委托</h3><button className="text-button" disabled={!!busy} onClick={() => void act('group', async () => { setQueried(await api.group(id)); onNotice('已读取任务组的实际状态。'); })}>核对任务组</button></div><p className="quiet">子任务受父任务与根任务的不可变权限约束，共享工具预算。取消当前任务会向其后代发出取消请求，全部停止仍需确认。</p>{scope ? <><div className="delegation-budget"><span>共享工具调用 <b>{count(scope.sharedBudget?.toolCallsUsed)} / {count(scope.sharedBudget?.toolCallsLimit)}</b></span><span>累计子任务 <b>{count(scope.sharedBudget?.childrenUsed)} / {count(scope.sharedBudget?.childrenLimit)}</b></span><span>当前深度 <b>{count(scope.depth)} / {count(scope.sharedBudget?.maxDepth)}</b></span></div><details className="technical-detail"><summary>不可变范围与共享预算</summary><span>父任务：{scope.parentTaskId ?? '未提供'}</span><span>根任务：{scope.rootTaskId ?? '未提供'}</span><span>能力范围：{scope.capabilities?.join('、') || '未提供'}</span><span>工具范围：{scope.tools?.join('、') || '未提供'}</span><pre>{JSON.stringify(scope.budget ?? {}, null, 2)}</pre>{draft.requestId && <span>创建请求：{draft.requestId}</span>}</details></> : <p className="quiet">后端尚未提供委托权限与共享预算，暂不能创建子任务。</p>}{group ? <><p className="delegation-state">{group.unknown ? '任务组存在未确认状态' : group.allStopped ? '任务组已确认全部停止' : group.pending ? '仍有子任务待完成或停止确认' : '父任务停止结果仍待确认'}</p>{group.children?.length ? <ul className="delegation-children">{group.children.map((child, i) => <li key={child.taskId ?? child.link?.request_id ?? i}><div><strong>{jobs.find(job => job.id === child.taskId)?.input.topic ?? '已登记的子任务'}</strong><small>{childStatus(child)}{child.link?.depth !== undefined ? ` · 深度 ${child.link.depth}` : ''}</small></div><button className="secondary" disabled={!!busy || !child.taskId} onClick={() => child.taskId && onSelect(child.taskId)}>查看子任务</button></li>)}</ul> : <p className="quiet">当前没有后代任务记录。</p>}</> : <p className="quiet">任务组状态尚未提供。</p>}{scope && !modeChoices.available && <p className="quiet">当前固定应用没有可用的子任务方式；原请求记录保留，不会改为其他方式。</p>}<form className="delegation-form" onSubmit={event => { event.preventDefault(); submit(); }}><label htmlFor="child-goal">子任务目标</label><textarea id="child-goal" rows={2} maxLength={2000} value={draft.goal} disabled={!!busy || !canCreate} onChange={event => edit({ goal: event.target.value })} placeholder="将当前目标拆分为一个有边界的子任务"/><div className="delegation-form-actions"><label>执行方式<select aria-label="子任务执行方式" value={modeChoices.selected} disabled={!!busy || !canCreate} onChange={event => edit({ mode: event.target.value as ChildDraft['mode'] })}>{modeChoices.modes.map(mode => <option key={mode} value={mode}>{delegationModeName(mode)}</option>)}{draft.requestId && !modeChoices.available && <option value={draft.mode}>原请求 {delegationModeName(draft.mode)}（当前不可委派）</option>}</select></label><button className="primary" disabled={!!busy || !canCreate || draft.goal.trim().length < 2}>{busy === 'delegate' ? '等待创建确认…' : draft.requestId ? '核对原创建请求' : '确认创建子任务'}</button></div></form><p className="quiet">通常每人最多 2 个活跃任务，父任务会占用一个名额；累计子任务与深度限制由服务端检查。{!canCreate && scope && '当前任务没有可用的委托授权。'}</p></section>;
}

function TaskDetail({ detail, busy, act, onNotice, onSelect, jobs, drafts, ownerId, onSourceSnapshot }: { ownerId: string; onSourceSnapshot: (snapshot: SynthesisSnapshot) => void; detail: JobDetail; busy: string; act: (name: string, work: () => Promise<void>) => Promise<void>; onNotice: (message: string) => void; onSelect: (id: string) => void; jobs: FactoryJob[]; drafts: Map<string, ChildDraft> }) {
  const { job, events, artifacts } = detail;
  const [answer, setAnswer] = useState('');
  const question = pendingQuestion(detail);
  const approval = pendingApproval(detail);
  const recordedRecovery = approvedRecovery(job);
  const orxState = orxExperimentState(detail);
  const orxApproval = job.approvalDetail?.toolName === 'orx_experiment_run';
  const inferenceRecovery = job.approvalDetail?.toolName === 'factory_resume_inference';
  const workflowWaiting = job.approvalDetail?.toolName === 'workflow_wait';
  const launchProofVerified = !orxApproval || orxState.kind === 'verified' && orxState.sourceVerified && orxState.experiment.taskId === job.id && !!orxState.experiment.projectId && !!orxState.experiment.experimentId;
  const remoteState = remoteHandoffState(detail);
  const nativeAvailable = nativeInteractionAvailable(detail);
  const awaitingReceiver = !nativeAvailable;
  useEffect(() => { setAnswer(''); }, [question?.id, question?.version]);
  const allowed = (action: string) => job.allowedActions?.includes(action) === true;
  const terminal = ['canceled', 'completed', 'failed'].includes(job.status);
  const mutate = (name: string, work: () => Promise<FactoryJob>, notice: string) => void act(name, async () => { await work(); onNotice(notice); });
  const control = (decision: Omit<ControlIntent, 'commandId'>) => void act(decision.action, async () => {
    const pointer = await persistCommandPointer(job.ownerId, job.id, decision);
    window.dispatchEvent(new Event('factory-controls-changed'));
    try {
      const receipt = await api.submitControl(job.ownerId, job.id, { ...decision, commandId: pointer.commandId });
      onNotice(commandNotice(receipt));
      if (decision.action === 'answer') setAnswer('');
    } finally { window.dispatchEvent(new Event('factory-controls-changed')); }
  });
  const metrics = detail.snapshot?.metrics;
  const metricEntries = metrics && typeof metrics === 'object' ? Object.entries(metrics as Record<string, unknown>).filter(([key, value]) => /^(tokens|inputTokens|outputTokens|elapsedSeconds|steps|durationMs|attempts|workerSeconds)$/.test(key) && (typeof value === 'number' || typeof value === 'string')) : [];
  const evidence = <><NativeCommandResult detail={detail}/><section><div className="section-heading"><h3>证据与产物</h3><span className="quiet">{job.evidenceKind ?? '证据类型未提供'}</span></div>{artifacts.length ? <ul className="artifact-list">{artifacts.map(artifact => <li key={artifact.id}><ArtifactDownload jobId={job.id} artifact={artifact}/><details className="technical-detail"><summary>完整性与记录时间</summary><span>SHA-256 {artifact.sha256}</span><span>记录于 {time(artifact.createdAt)}</span></details></li>)}</ul> : <p className="list-empty">尚无产物。执行完成也不自动代表已有有效研究证据。</p>}</section><LiteratureEvidencePanel detail={detail}/>{job.status === 'completed' && detail.literatureEvidence !== undefined && <SynthesisJourney key={job.id} ownerId={ownerId} sourceTaskId={job.id} api={api.synthesis} onSnapshot={onSourceSnapshot} disabled={!!busy}/>}<SynthesisReport evidence={detail.synthesisEvidence}/><ComparisonReport evidence={detail.comparisonEvidence} ownerId={ownerId} taskId={job.id} planId={job.planId ?? ''} artifacts={artifacts}/><OrxExperimentPanel detail={detail}/>{detail.orxExperiment === undefined && <EvaluationEvidence detail={detail}/>}</>;
  return <><div className="task-title"><div className="section-heading"><span className="quiet">任务记录</span><Badge value={job.status} label={remoteState.kind === 'pending' ? '等待接收端审查' : remoteState.kind === 'invalid' ? '远端状态待核对' : undefined}/></div><h2>{job.input.topic}</h2><p>{detail.orxExperiment ? 'ORX 本地 toy 实验 · 实际执行与研究结论分别验证' : job.runtime === 'demo' ? '确定性演示 · 结果为合成数据' : '真实运行 · 证据需要单独验证'}</p>{job.executionPlacement && <p className="remote-placement">执行位置：{job.executionPlacement.targetRef} · {job.executionPlacement.kind === 'remote-factory' ? '远端 Factory' : job.executionPlacement.kind}。执行结果与停止确认以接收端记录为准。</p>}<div className="task-facts"><span>创建 {time(job.createdAt)}</span><span>尝试 {job.attempt ?? '未知'}</span><span>验证 {job.validationStatus ?? '未提供'}</span></div></div><div className="task-controls">{!terminal && <button className="secondary danger" disabled={!!busy || !allowed('cancel') || job.status === 'canceling'} onClick={() => control({ action: 'cancel' })}>{job.status === 'canceling' ? '等待取消结果' : '请求取消'}</button>}<button className="secondary" disabled={!!busy || !allowed('reconcile')} onClick={() => mutate('reconcile', () => api.reconcile(job.id), '已请求核对状态，以新的任务记录为准。')}>核对执行状态</button>{!job.allowedActions && <span className="quiet">可用操作待服务端确认</span>}</div>{job.error && <ErrorMessage message={job.error}/>} {job.status === 'canceling' && <div className="state-note">服务端已接受取消请求，不代表执行已经停止。状态更新后才能确认释放结果。</div>}{job.status === 'completed' && <div className="state-note">执行已完成。研究结论是否通过验证：{job.validationStatus ?? '后端尚未提供验证结论'}。</div>}{nativeAvailable && job.status === 'waiting_input' && <section className="attention-panel"><h3>需要你的回答</h3><p>{question?.text ?? job.question ?? '问题内容尚未提供。'}</p>{question ? <form onSubmit={event => { event.preventDefault(); control({ action: 'answer', requirementId: question.id, version: question.version, answer: answer.trim() }); }}><label htmlFor="job-answer">回答</label><textarea id="job-answer" value={answer} onChange={event => setAnswer(event.target.value)} rows={3} disabled={!!busy}/><button className="primary" disabled={!!busy || !allowed('answer') || !answer.trim()}>提交回答</button></form> : <p className="quiet">缺少问题标识或版本，暂不能安全提交。</p>}</section>}{nativeAvailable && recordedRecovery && <ApprovedRecoveryPanel recovery={recordedRecovery} busy={!!busy} submit={control}/>}
    {nativeAvailable && !recordedRecovery && !workflowWaiting && job.status === 'waiting_approval' && <section className="attention-panel"><h3>{inferenceRecovery ? '推理服务暂时不可用' : '等待执行审批'}</h3><p>{approval?.scope ?? job.approval?.scope ?? '审批范围尚未提供。'}</p><p className="quiet">此决定只针对本次执行，不会发布共享材料。</p>{orxApproval && <p className="quiet">本次请求将运行任务自有的真实 ORX toy 实验。先<a href="#orx-experiment-evidence">核对下方固定源码、命令与数据哈希</a>；任务预算与停止记录由服务端保持。{!launchProofVerified && ' 当前来源凭据尚未完整核对，暂不能同意运行。'}</p>}{approval ? <div className="button-row"><button className="primary" disabled={!!busy || !allowed('approve') || !launchProofVerified} onClick={() => control({ action: 'approve', requirementId: approval.id, version: approval.version, approved: true })}>{inferenceRecovery ? '恢复本次推理' : '同意本次请求'}</button><button className="secondary" disabled={!!busy || !allowed('approve')} onClick={() => control({ action: 'approve', requirementId: approval.id, version: approval.version, approved: false })}>{inferenceRecovery ? '停止本任务' : '拒绝'}</button></div> : <p className="quiet">缺少审批标识或版本，暂不能安全提交。</p>}</section>}<RemoteHandoffPanel detail={detail} busy={busy} act={act} onNotice={onNotice}/><div className="detail-sections">{terminal && evidence}<WorkflowPanel ownerId={ownerId} taskId={job.id} api={api.workflows} disabled={!!busy}/>{!awaitingReceiver && (terminal ? <details className="task-secondary-detail"><summary>任务委托与子任务记录</summary><DelegationPanel detail={detail} busy={busy} act={act} onNotice={onNotice} onSelect={onSelect} jobs={jobs} drafts={drafts}/></details> : <DelegationPanel detail={detail} busy={busy} act={act} onNotice={onNotice} onSelect={onSelect} jobs={jobs} drafts={drafts}/>)}{terminal ? <details className="task-secondary-detail"><summary>执行时间线与完整历史</summary><EventTimeline key={job.id} jobId={job.id} latest={events} replayAvailable={!awaitingReceiver}/></details> : <EventTimeline key={job.id} jobId={job.id} latest={events} replayAvailable={!awaitingReceiver}/>}{!terminal && evidence}<UsageLedgerPanel detail={detail}/><section><h3>执行指标</h3>{metricEntries.length ? <dl className="execution-metrics">{metricEntries.map(([key, value]) => <div key={key}><dt>{({ tokens: '令牌总数', inputTokens: '输入令牌', outputTokens: '输出令牌', elapsedSeconds: '耗时（秒）', steps: '执行步骤', durationMs: '耗时（毫秒）', attempts: '尝试次数', workerSeconds: '工作耗时（秒）' } as Record<string, string>)[key] ?? key}{job.runtime === 'demo' ? '（合成）' : ''}</dt><dd>{String(value)}</dd></div>)}</dl> : <p className="list-empty">后端尚未提供执行指标。</p>}</section><details className="technical-detail"><summary>任务引用</summary><span>任务 {job.id}</span><span>方案 {job.planId ?? '未提供'}</span><span>定义 {job.definitionId} v{job.definitionVersion}</span></details></div></>;
}
