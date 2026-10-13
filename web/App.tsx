import { useCallback, useEffect, useRef, useState, type ComponentType, type ReactNode } from 'react';
import { api, ApiError } from './api.js';
import { FeeVisibility } from './FeeVisibility.js';
import { browserAuthConfig, clearBrowserSession, consumeSigninFailure, startBrowserLogin, subscribeSessionExpiry, type BrowserAuthConfig } from './browserAuth.js';
import { defaultNavigation, readWorkspaceRoute, sameWorkspaceRoute, workspaceUrl, type WorkspaceNavigation, type WorkspaceRoute, type WorkspaceTab } from './workspaceNavigation.js';
import { ErrorMessage, time } from './workspaceUI.js';
import type { FactoryJob, FactoryMaterial, FactoryStatus, JobDetail, ExecutionTarget, User } from './models.js';
import type { ChildDraft } from './TaskWorkspace.js';
import type { ComposerSeed } from './ApplicationComposer.js';

export interface WorkspaceSessionProps { user: User; logout: () => void; sessionBusy: boolean; sessionError: string }
export interface WorkspaceContext {
  user: User; route: WorkspaceRoute; navigate: (patch: Partial<WorkspaceRoute>) => void;
  status?: FactoryStatus; materials: FactoryMaterial[]; targets: ExecutionTarget[]; jobs: FactoryJob[];
  detail?: JobDetail; detailError: string; busy: string; syncedAt: string;
  act: (name: string, work: () => Promise<void>) => Promise<void>;
  notice: (message: string) => void; retry: () => void; onTask: (task: string) => void;
  drafts: Map<string, ChildDraft>; onCompose?: (seed: ComposerSeed, notice: string) => void;
}

function describe(error: unknown) {
  if (error instanceof ApiError && error.code === 'OFFLINE') return '无法连接服务。已保留上次读取的记录；请恢复网络后重新连接，未确认的操作须核对原请求。';
  if (error instanceof ApiError && error.code === 'POLICY_UNSET') return '临时任务审批规则尚未配置，服务端拒绝创建。请联系管理员；预检方案已保留。';
  return error instanceof Error ? error.message : '操作未确认，请重试。';
}
export default function App({ workspace: WorkspaceComponent = Workspace }: { workspace?: ComponentType<WorkspaceSessionProps> }) {
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
  if (user && authConfig) return <WorkspaceComponent key={user.id} user={user} logout={() => void logout()} sessionBusy={busy} sessionError={error}/>;
  return <div className="login-page"><div className="login-brand"><span className="brand-symbol" aria-hidden="true">研</span><span>Agent Factory</span></div><section className="login-panel"><p className="quiet">Agent Factory 工作台</p><h1>从任务目标，<br/>到可核对的结果。</h1><p>选择应用，描述任务目标后开始。进度与结果都在任务记录中。</p>{loginMode === 'demo' ? <div className="demo-notice"><strong>{authConfig?.developmentOnly ? '开发模拟登录（仅本地）' : '本地演示入口'}</strong><span>确定性运行与合成结果用于验证流程，不代表真实研究已完成。真实模型调用需另行启用。</span></div> : <div className="demo-notice"><strong>{loginMode === 'live' ? '真实运行环境' : '环境状态待确认'}</strong><span>{loginMode === 'live' ? authConfig?.enabled ? '使用组织的统一身份认证登录，账号权限由服务端核对。' : '请使用服务端配置的身份认证入口。演示身份登录已关闭。' : '环境模式尚未确认，演示登录不可用。'}</span></div>}<ErrorMessage message={error} retry={() => setGeneration(n => n + 1)}/>{authConfig?.enabled && <div className="login-actions"><button className="primary" disabled={busy || loading} onClick={() => void ssoLogin()}>{busy ? '正在前往登录…' : authConfig.developmentOnly ? '选择开发测试身份' : '使用企业账号登录'}</button></div>}{authConfig?.enabled === false && loginMode === 'demo' && <div className="login-actions">{([['alice', '研究员 Alice'], ['bob', '研究员 Bob'], ['manager', '管理员']] as const).map(([id, label]) => <button key={id} className={id === 'alice' ? 'primary' : 'secondary'} disabled={busy || loading} onClick={() => void login(id)}>{label}</button>)}</div>}{loading ? <p role="status" className="quiet">正在检查会话…</p> : (!authConfig || !loginMode) && <button className="secondary" onClick={() => setGeneration(n => n + 1)}>重新检查环境</button>}<p className="login-footnote">账号权限与任务范围由服务端检查。</p></section></div>;
}

export function Workspace({ user, logout, sessionBusy, sessionError, navigation = defaultNavigation, children, onCompose }: WorkspaceSessionProps & { navigation?: WorkspaceNavigation; children?: (context: WorkspaceContext) => ReactNode; onCompose?: WorkspaceContext['onCompose'] }) {
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [route, setRoute] = useState(() => readWorkspaceRoute(new URL(window.location.href), user.role === 'manager', navigation));
  const routeRef = useRef(route);
  const navigate = (patch: Partial<WorkspaceRoute>) => {
    const next = { ...routeRef.current, ...patch };
    if (sameWorkspaceRoute(next, routeRef.current)) return;
    window.history.pushState(null, '', workspaceUrl(new URL(window.location.href), next, navigation));
    routeRef.current = next; setRoute(next);
  };
  const tab = route.tab;
  const selected = route.task;
  const setTab = (tab: WorkspaceTab) => navigate({ tab });
  const setSelected = (task: string) => { navigate({ tab: 'research', task }); setActionError(''); };
  useEffect(() => {
    const restore = () => {
      const next = readWorkspaceRoute(new URL(window.location.href), user.role === 'manager', navigation);
      routeRef.current = next; setRoute(next);
    };
    // Normalize unknown/unauthorized views without adding a history entry.
    window.history.replaceState(null, '', workspaceUrl(new URL(window.location.href), routeRef.current, navigation));
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, [user.role, navigation]);
  const [status, setStatus] = useState<FactoryStatus>();
  const [materials, setMaterials] = useState<FactoryMaterial[]>([]);
  const [targets, setTargets] = useState<ExecutionTarget[]>([]);
  const [jobs, setJobs] = useState<FactoryJob[]>([]);
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
  const context: WorkspaceContext = { user, route, navigate, status, materials, targets, jobs, detail, detailError, busy, syncedAt, act, notice: setNotice, retry, onTask: setSelected, drafts: childDrafts.current, onCompose };
  const tabs = navigation.tabs;
  return <FeeVisibility enabled={status?.feeManagementEnabled === true}><div className="factory-shell">
    <aside className="sidebar"><div className="brand"><span className="brand-symbol" aria-hidden="true">研</span><div><strong>Agent Factory</strong><small>应用与任务</small></div></div>
    <nav aria-label="工作区"><span className="nav-group-label">工作区</span><button aria-current={tab === 'catalog' || navigation.applicationTabs?.includes(tab) ? 'page' : undefined} onClick={() => setTab('catalog')}>应用</button><button aria-current={['resources', 'models', 'connections'].includes(tab) ? 'page' : undefined} onClick={() => setTab('resources')}>资源</button><button aria-current={tab === 'research' ? 'page' : undefined} onClick={() => setTab('research')}>任务</button>
      <button className="mobile-nav-toggle" aria-expanded={navigationOpen} aria-controls="secondary-navigation" onClick={() => setNavigationOpen(value => !value)}>{navigationOpen ? '收起高级与管理入口' : '高级与管理'}</button>
      <div id="secondary-navigation" className={`secondary-navigation ${navigationOpen ? 'expanded' : ''}`}><span className="nav-group-label">高级工具</span>{(navigation.advancedTabs ?? ['schedules', 'storage']).map(value => <button key={value} aria-current={tab === value ? 'page' : undefined} onClick={() => setTab(value)}>{tabs[value]}</button>)}<button aria-current={tab === 'developer' ? 'page' : undefined} onClick={() => setTab('developer')}>开发者装配</button>{<><span className="nav-group-label">共享应用与材料</span>{(['applications', 'materials', 'reviews'] as const).map(value => <button key={value} aria-current={tab === value ? 'page' : undefined} onClick={() => setTab(value)}>{tabs[value]}</button>)}</>}</div>
    </nav><div className="sidebar-context"><span className="sidebar-line"/><p>能力来自已发布材料。<br/>连接只在授权范围内使用。</p></div><div className="identity"><div className="avatar" aria-hidden="true">{user.name.slice(0, 1)}</div><div><strong>{user.name}</strong><small>{user.role === 'manager' ? '管理员' : '成员'}</small></div><button className="logout" disabled={sessionBusy || !!busy} onClick={logout}>退出</button></div></aside>
    <main className="workspace"><header className="workspace-header"><div><span className="quiet">工作区 / </span><strong>{tabs[tab]}</strong></div><div className="sync-state"><span className={`connection-dot ${syncError ? 'disconnected' : ''}`} aria-hidden="true"/>{syncError ? '页面同步中断' : syncedAt ? '页面已同步' : '页面同步中'}<button className="text-button" onClick={retry} disabled={!!busy}>刷新</button></div></header>
    <div className="workspace-body"><div className="runtime-strip"><div><strong>{status?.mode === 'demo' ? '演示运行' : status?.mode === 'live' ? '真实运行模式' : '运行模式待确认'}</strong><span>{status?.mode === 'demo' ? '开发验证环境 · 实际模型与证据状态以任务记录为准' : status?.mode === 'live' ? '实际执行与证据状态以任务记录为准' : '等待服务端确认，尚未创建任务'}</span></div><span className="integration">{status?.integration ?? '集成状态未知'}</span></div>
      <ErrorMessage message={sessionError}/><ErrorMessage message={syncError} retry={retry}/><ErrorMessage message={actionError}/>{notice && <div className="success-message" role="status">{notice}</div>}
      {children?.(context)}<footer className="workspace-footer"><span>最近同步 {time(syncedAt)}</span><span>任务执行与结果验证分别记录</span></footer>
    </div></main></div></FeeVisibility>;
}
