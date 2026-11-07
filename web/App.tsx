import { useCallback, useEffect, useRef, useState, type ComponentType, type ReactNode } from 'react';
import { api, ApiError } from './api.js';
import { authEpoch, browserAuthConfig, BrowserAuthError, clearBrowserSession, consumeSigninFailure, startBrowserLogin, startLocalLogin, subscribeSessionExpiry, type BrowserAuthConfig } from './browserAuth.js';
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
  const [authConfig, setAuthConfig] = useState<BrowserAuthConfig>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
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
        if (!config.enabled) { setError('浏览器身份认证尚未配置，请联系服务维护者。'); return; }
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
  async function localLogin() {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    const submittedPassword = password; setPassword('');
    try { await startLocalLogin(username, submittedPassword); setUser(await api.session()); }
    catch (error) { setError(error instanceof BrowserAuthError && error.status === 401 ? '登录失败，请核对用户名和密码。' : '登录暂时不可用，请重试。'); }
    finally { lock.current = false; setBusy(false); }
  }
  async function logout() {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try { await api.logout(); clearBrowserSession(); setUser(null); } catch (e) { setError(describe(e)); }
    finally { lock.current = false; setBusy(false); }
  }
  if (user && authConfig) return <WorkspaceComponent key={user.id} user={user} logout={() => void logout()} sessionBusy={busy} sessionError={error}/>;
  return <div className="login-page"><div className="login-brand"><span className="brand-symbol" aria-hidden="true">F</span><span>Agent Factory</span></div><section className="login-panel"><p className="quiet">Agent Factory 工作台</p><h1>从任务目标，<br/>到可核对的结果。</h1><p>描述目标即可开始对话，直接查看助手的执行过程与结果。</p>
    <div className="auth-notice"><strong>{authConfig?.enabled ? '账号登录' : '身份认证未就绪'}</strong><span>{authConfig?.enabled ? '使用已配置的登录方式，账号权限由服务端核对。' : '需要配置身份认证后才能登录。'}</span></div>
    <ErrorMessage message={error} retry={() => setGeneration(n => n + 1)}/>
    {authConfig?.localLoginEnabled && <form onSubmit={event => { event.preventDefault(); void localLogin(); }}><fieldset disabled={busy || loading}>
      <label>用户名<input name="username" autoComplete="username" required value={username} onChange={event => setUsername(event.target.value)}/></label>
      <label>密码<input name="password" type="password" autoComplete="current-password" required value={password} onChange={event => setPassword(event.target.value)}/></label>
      <button className="primary wide" type="submit">{busy ? '正在登录…' : '登录'}</button>
    </fieldset></form>}
    {authConfig?.oidcEnabled && <div className="login-actions"><button className="primary" disabled={busy || loading} onClick={() => void ssoLogin()}>使用企业账号登录</button></div>}
    {loading ? <p role="status" className="quiet">正在检查会话…</p> : !authConfig?.enabled && <button className="secondary" onClick={() => setGeneration(n => n + 1)}>重新检查环境</button>}
    <p className="login-footnote">账号权限与任务范围由服务端检查。</p></section></div>;
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
