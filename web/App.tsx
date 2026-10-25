import { useCallback, useEffect, useRef, useState, type ComponentType, type ReactNode } from 'react';
import { api, ApiError } from './api.js';
import { compareJobOrder, mergeJobHistory } from './jobHistory.js';
import { FeeVisibility } from './FeeVisibility.js';
import { browserAuthConfig, clearBrowserSession, consumeSigninFailure, startBrowserLogin, subscribeSessionExpiry, type BrowserAuthConfig } from './browserAuth.js';
import { defaultNavigation, readWorkspaceRoute, sameWorkspaceRoute, workspaceUrl, type WorkspaceNavigation, type WorkspaceRoute, type WorkspaceTab } from './workspaceNavigation.js';
import { ErrorMessage, time } from './workspaceUI.js';
import type { JobSummary, FactoryMaterial, FactoryStatus, JobDetail, ExecutionTarget, User } from './models.js';
import type { ChildDraft } from './TaskWorkspace.js';
import type { ComposerSeed } from './ApplicationComposer.js';

export interface WorkspaceSessionProps { user: User; logout: () => void; sessionBusy: boolean; sessionError: string }
export interface WorkspaceContext {
  user: User; route: WorkspaceRoute; navigate: (patch: Partial<WorkspaceRoute>) => void;
  status?: FactoryStatus; materials: FactoryMaterial[]; targets: ExecutionTarget[]; jobs: JobSummary[];
  jobsLoaded: boolean; jobsError: string; historyError: string; historyLoading: boolean; nextCursor: string | null; loadEarlier: () => void;
  detail?: JobDetail; detailError: string; busy: string; syncedAt: string;
  act: (name: string, work: () => Promise<void>) => Promise<void>;
  notice: (message: string) => void; retry: () => void; onTask: (task: string) => void;
  drafts: Map<string, ChildDraft>; onCompose?: (seed: ComposerSeed, notice: string) => void;
}

function describe(error: unknown) {
  if (error instanceof ApiError && error.code === 'OFFLINE') return '无法连接服务。已保留上次读取的记录；请恢复网络后重新连接，未确认的操作须核对原请求。';
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
  return <div className="login-page"><div className="login-brand"><span className="brand-symbol" aria-hidden="true">F</span><span>Agent Factory</span></div><section className="login-panel"><p className="quiet">Agent Factory 工作台</p><h1>从任务目标，<br/>到可核对的结果。</h1><p>选择应用，描述任务目标后开始。进度与结果都在任务记录中。</p>{loginMode === 'demo' ? <div className="demo-notice"><strong>{authConfig?.developmentOnly ? '开发模拟登录（仅本地）' : '本地演示入口'}</strong><span>确定性运行与合成结果用于验证流程，不代表真实任务已完成。真实模型调用需另行启用。</span></div> : <div className="demo-notice"><strong>{loginMode === 'live' ? '真实运行环境' : '环境状态待确认'}</strong><span>{loginMode === 'live' ? authConfig?.enabled ? '使用组织的统一身份认证登录，账号权限由服务端核对。' : '请使用服务端配置的身份认证入口。演示身份登录已关闭。' : '环境模式尚未确认，演示登录不可用。'}</span></div>}<ErrorMessage message={error} retry={() => setGeneration(n => n + 1)}/>{authConfig?.enabled && <div className="login-actions"><button className="primary" disabled={busy || loading} onClick={() => void ssoLogin()}>{busy ? '正在前往登录…' : authConfig.developmentOnly ? '选择开发测试身份' : '使用企业账号登录'}</button></div>}{authConfig?.enabled === false && loginMode === 'demo' && <div className="login-actions">{([['alice', '成员 Alice'], ['bob', '成员 Bob'], ['manager', '管理员']] as const).map(([id, label]) => <button key={id} className={id === 'alice' ? 'primary' : 'secondary'} disabled={busy || loading} onClick={() => void login(id)}>{label}</button>)}</div>}{loading ? <p role="status" className="quiet">正在检查会话…</p> : (!authConfig || !loginMode) && <button className="secondary" onClick={() => setGeneration(n => n + 1)}>重新检查环境</button>}<p className="login-footnote">账号权限与任务范围由服务端检查。</p></section></div>;
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
  const setSelected = (task: string) => { navigate({ tab: 'tasks', task }); setActionError(''); };
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
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [detail, setDetail] = useState<JobDetail>();
  const [readErrors, setReadErrors] = useState({ status: '', materials: '', jobs: '', targets: '' });
  const syncError = Object.values(readErrors).some(Boolean);
  const [jobsLoaded, setJobsLoaded] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const historyRequest = useRef<AbortController | null>(null);
  const historyStarted = useRef(false);
  const latestHead = useRef<JobSummary | null>(null);
  useEffect(() => () => { historyRequest.current?.abort(); }, []);
  const loadEarlier = async () => {
    if (!nextCursor || historyRequest.current) return;
    const controller = new AbortController();
    historyRequest.current = controller; historyStarted.current = true;
    setHistoryLoading(true); setHistoryError('');
    try {
      const page = await api.jobs(controller.signal, nextCursor);
      if (controller.signal.aborted) return;
      setJobs(current => mergeJobHistory(current, page.items)); setNextCursor(page.nextCursor);
    } catch (error) { if (!controller.signal.aborted) setHistoryError(describe(error)); }
    finally {
      if (!controller.signal.aborted) { historyRequest.current = null; setHistoryLoading(false); }
    }
  };
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
    const timers = new Map<string, ReturnType<typeof setTimeout>>();
    function start<T>(key: keyof typeof readErrors, read: () => Promise<T>, apply: (value: T) => void) {
      async function poll() {
        try {
          const value = await read();
          if (controller.signal.aborted) return;
          apply(value); setReadErrors(current => ({ ...current, [key]: '' }));
          setSyncedAt(new Date().toISOString());
        } catch (error) {
          if (!controller.signal.aborted) setReadErrors(current => ({ ...current, [key]: describe(error) }));
        }
        if (!controller.signal.aborted) timers.set(key, setTimeout(() => void poll(), 5000));
      }
      void poll();
    }
    start('status', () => api.status(controller.signal), setStatus);
    start('materials', () => api.materials(controller.signal), setMaterials);
    start('targets', () => api.executionTargets(controller.signal), setTargets);
    start('jobs', async () => {
      const head = await api.jobs(controller.signal);
      const boundary = latestHead.current;
      const items = [...head.items];
      let page = head;
      // A full head page can hide new rows between it and the history already loaded.
      // Follow keyset pages to the previous head boundary before advancing that boundary.
      while (!controller.signal.aborted && boundary && page.nextCursor && page.items.length &&
        compareJobOrder(page.items[page.items.length - 1], boundary) > 0) {
        page = await api.jobs(controller.signal, page.nextCursor);
        items.push(...page.items);
      }
      return { ...head, items, head: head.items[0] };
    }, page => {
      latestHead.current = page.head ?? latestHead.current;
      setJobs(current => mergeJobHistory(current, page.items)); setJobsLoaded(true);
      if (!historyStarted.current) setNextCursor(page.nextCursor);
    });
    return () => { controller.abort(); timers.forEach(clearTimeout); };
  }, [refresh]);
  useEffect(() => {
    if (!selected) { setDetail(undefined); setDetailError(''); return; }
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
  const context: WorkspaceContext = { user, route, navigate, status, materials, targets, jobs, jobsLoaded, jobsError: readErrors.jobs, historyError, historyLoading, nextCursor, loadEarlier: () => void loadEarlier(), detail, detailError, busy, syncedAt, act, notice: setNotice, retry, onTask: setSelected, drafts: childDrafts.current, onCompose };
  const tabs = navigation.tabs;
  return <FeeVisibility enabled={status?.feeManagementEnabled === true}><div className="factory-shell">
    <aside className="sidebar"><div className="brand"><span className="brand-symbol" aria-hidden="true">F</span><div><strong>Agent Factory</strong><small>应用与任务</small></div></div>
    <nav aria-label="工作区"><span className="nav-group-label">工作区</span><button aria-current={tab === 'catalog' || navigation.applicationTabs?.includes(tab) ? 'page' : undefined} onClick={() => setTab('catalog')}>应用</button><button aria-current={['resources', 'models', 'connections'].includes(tab) ? 'page' : undefined} onClick={() => setTab('resources')}>资源</button><button aria-current={tab === 'tasks' ? 'page' : undefined} onClick={() => setTab('tasks')}>任务</button>
      <button className="mobile-nav-toggle" aria-expanded={navigationOpen} aria-controls="secondary-navigation" onClick={() => setNavigationOpen(value => !value)}>{navigationOpen ? '收起高级与管理入口' : '高级与管理'}</button>
      <div id="secondary-navigation" className={`secondary-navigation ${navigationOpen ? 'expanded' : ''}`}><span className="nav-group-label">高级工具</span>{(navigation.advancedTabs ?? ['schedules', 'storage']).map(value => <button key={value} aria-current={tab === value ? 'page' : undefined} onClick={() => setTab(value)}>{tabs[value]}</button>)}<button aria-current={tab === 'developer' ? 'page' : undefined} onClick={() => setTab('developer')}>开发者装配</button>{<><span className="nav-group-label">共享应用与材料</span>{(['applications', 'materials', 'reviews'] as const).map(value => <button key={value} aria-current={tab === value ? 'page' : undefined} onClick={() => setTab(value)}>{tabs[value]}</button>)}</>}{user.role === 'manager' && <><span className="nav-group-label">账号</span><button aria-current={tab === 'accounts' ? 'page' : undefined} onClick={() => setTab('accounts')}>账号管理</button></>}</div>
    </nav><div className="sidebar-context"><span className="sidebar-line"/><p>能力来自已发布材料。<br/>连接只在授权范围内使用。</p></div><div className="identity"><div className="avatar" aria-hidden="true">{user.name.slice(0, 1)}</div><div><strong>{user.name}</strong><small>{user.role === 'manager' ? '账号管理员' : '成员'}</small></div><button className="logout" disabled={sessionBusy || !!busy} onClick={logout}>退出</button></div></aside>
    <main className="workspace"><header className="workspace-header"><div><span className="quiet">工作区 / </span><strong>{tabs[tab]}</strong></div><div className="sync-state"><span className={`connection-dot ${syncError ? 'disconnected' : ''}`} aria-hidden="true"/>{syncError ? '部分区域更新失败' : syncedAt ? '页面已同步' : '页面同步中'}<button className="text-button" onClick={retry} disabled={!!busy}>刷新</button></div></header>
    <div className="workspace-body"><div className="runtime-strip"><div><strong>{status?.mode === 'demo' ? '演示运行' : status?.mode === 'live' ? '真实运行模式' : '运行模式待确认'}</strong><span>{status?.mode === 'demo' ? '开发验证环境 · 实际模型与证据状态以任务记录为准' : status?.mode === 'live' ? '实际执行与证据状态以任务记录为准' : '等待服务端确认，尚未创建任务'}</span></div><span className="integration">{status?.integration ?? '集成状态未知'}</span></div>
      <ErrorMessage message={sessionError}/><ErrorMessage message={readErrors.status && `运行状态更新失败：${readErrors.status}`} retry={retry}/>{['catalog', 'developer', 'materials', 'applications'].includes(tab) && <ErrorMessage message={readErrors.materials && `材料目录更新失败：${readErrors.materials}`} retry={retry}/>}<ErrorMessage message={readErrors.targets && `执行目标更新失败：${readErrors.targets}`} retry={retry}/><ErrorMessage message={actionError}/>{notice && <div className="success-message" role="status">{notice}</div>}
      {children?.(context)}<footer className="workspace-footer"><span>最近成功读取 {time(syncedAt)}</span><span>任务执行与结果验证分别记录</span></footer>
    </div></main></div></FeeVisibility>;
}
