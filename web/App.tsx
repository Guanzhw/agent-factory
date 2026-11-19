import { useCallback, useEffect, useRef, useState, type ComponentType, type ReactNode } from 'react';
import { api, ApiError } from './api.js';
import { authEpoch, BrowserAuthError, clearBrowserSession, readBrowserSession, startLocalLogin, subscribeSessionExpiry } from './browserAuth.js';
import { defaultNavigation, readWorkspaceRoute, sameWorkspaceRoute, workspaceUrl, type WorkspaceNavigation, type WorkspaceRoute, type WorkspaceTab } from './workspaceNavigation.js';
import { clearModelSettingsDraft } from './modelSettingsDraft.js';
import { ErrorMessage } from './workspaceUI.js';
import type { User } from './models.js';
export interface WorkspaceSessionProps { user: User; logout: () => void; sessionBusy: boolean; sessionError: string }
export interface WorkspaceContext {
  feedback?: ReactNode; selectTab: (tab: WorkspaceTab) => void;
  user: User; route: WorkspaceRoute; navigate: (patch: Partial<WorkspaceRoute>) => void;
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
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const lock = useRef(false);
  const [generation, setGeneration] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setUser(null);
    async function load() {
      try {
        const current = await readBrowserSession(controller.signal);
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
  async function localLogin() {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    const submittedPassword = password; setPassword('');
    try {
      await startLocalLogin(username, submittedPassword);
      const current = await readBrowserSession();
      if (!current) throw new BrowserAuthError(401);
      setUser(current);
    }
    catch (error) { setError(error instanceof BrowserAuthError && error.status === 401 ? '登录失败，请核对用户名和密码。' : '登录暂时不可用，请重试。'); }
    finally { lock.current = false; setBusy(false); }
  }
  async function logout() {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try { await api.logout(); clearBrowserSession(); setUser(null); } catch (e) { setError(describe(e)); }
    finally { lock.current = false; setBusy(false); }
  }
  if (user) return <WorkspaceComponent key={user.id} user={user} logout={() => void logout()} sessionBusy={busy} sessionError={error}/>;
  return <div className="login-page"><div className="login-brand"><span className="brand-symbol" aria-hidden="true">F</span><span>Agent Factory</span></div><section className="login-panel"><h1>登录工作台</h1>
    <ErrorMessage message={error} retry={() => setGeneration(n => n + 1)}/>
    <form onSubmit={event => { event.preventDefault(); void localLogin(); }}><fieldset disabled={busy || loading}>
      <label>用户名<input name="username" autoComplete="username" required value={username} onChange={event => setUsername(event.target.value)}/></label>
      <label>密码<input name="password" type="password" autoComplete="current-password" required value={password} onChange={event => setPassword(event.target.value)}/></label>
      <button className="primary wide" type="submit">{busy ? '正在登录…' : '登录'}</button>
    </fieldset></form>
    {loading && <p role="status" className="quiet">正在检查会话…</p>}</section></div>;
}

export function Workspace({ user, navigation = defaultNavigation, applicationView }: WorkspaceSessionProps & { navigation?: WorkspaceNavigation; applicationView?: (context: WorkspaceContext) => ReactNode }) {
  useEffect(() => {
    const epoch = authEpoch();
    return () => { if (authEpoch() !== epoch) clearModelSettingsDraft(user.id); };
  }, [user.id]);
  const [route, setRoute] = useState(() => readWorkspaceRoute(new URL(window.location.href), user.role === 'manager', navigation));
  const routeRef = useRef(route);
  const navigate = useCallback((patch: Partial<WorkspaceRoute>) => {
    const next = { ...routeRef.current, ...patch };
    if (sameWorkspaceRoute(next, routeRef.current)) return;
    window.history.pushState(null, '', workspaceUrl(new URL(window.location.href), next, navigation));
    routeRef.current = next; setRoute(next);
  }, [navigation]);
  useEffect(() => {
    const restore = () => {
      const next = readWorkspaceRoute(new URL(window.location.href), user.role === 'manager', navigation);
      routeRef.current = next; setRoute(next);
    };
    window.history.replaceState(null, '', workspaceUrl(new URL(window.location.href), routeRef.current, navigation));
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, [user.role, navigation]);
  return applicationView?.({ user, route, navigate, selectTab: tab => navigate({ tab, resource: undefined }) });
}
