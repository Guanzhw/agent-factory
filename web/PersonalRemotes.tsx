import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api.js';
import { PersonalAgentSessions } from './PersonalAgentSessions.js';
import { PERSONAL_PROVIDER, ORX_PERSONAL_PROVIDER } from './personalAgentApi.js';
import { CredentialForm } from './CredentialForm.js';
import { useCommandKeys } from './commandKeys.js';
import { personalRemoteApi, remoteCanBind, definitivelyRejected, RemoteRequestError, type PersonalCredential, type PersonalRemote, type RemoteProvider } from './personalRemoteApi.js';
import type { FactoryJob, User } from './models.js';
const statusNames: Record<string, string> = { configured: '配置已保存，尚未验证', verified: '只读验证有效', expired: '验证已过期，需重新验证并绑定', revoked: '已撤销', credential_unavailable: '凭据不可用或已轮换', policy_changed: '部署策略已变更', unavailable: '当前不可用', failed: '验证未通过' };
function validOrigin(value: string) { try { const url = new URL(value); return url.protocol === 'https:' && url.origin === value && !url.username && !url.password && !url.port; } catch { return false; } }
export function PersonalRemotes({ user, jobs, onChanged, onTask, researchSetup = false }: { user: User; jobs: FactoryJob[]; onChanged: () => void; onTask?: (id: string) => void; researchSetup?: boolean }) {
  const [providers, setProviders] = useState<RemoteProvider[]>([]); const [remotes, setRemotes] = useState<PersonalRemote[]>([]);
  const [ready, setReady] = useState(false); const [vault, setVault] = useState(false); const [error, setError] = useState('');
  const [authMode, setAuthMode] = useState<'' | 'bearer' | 'basic-proxy'>(researchSetup ? 'bearer' : ''); const [sessionTemplateId, setSessionTemplateId] = useState('');
  const [projectCreation, setProjectCreation] = useState(researchSetup);
  const [providerId, setProviderId] = useState(researchSetup ? ORX_PERSONAL_PROVIDER : ''); const [origin, setOrigin] = useState(''); const [projectId, setProjectId] = useState('');
  const [credentials, setCredentials] = useState<PersonalCredential[]>([]);
  const [credential, setCredential] = useState<PersonalCredential | null>(null); const [showCredential, setShowCredential] = useState(false);
  const [editing, setEditing] = useState<string | undefined>(); const [busy, setBusy] = useState(false); const lock = useRef(false);
  const [refresh, setRefresh] = useState(0); const [notice, setNotice] = useState(''); const [taskId, setTaskId] = useState('');
  const keys = useCommandKeys(user.id);
  const pendingStorage = `factory-remote-pending:${encodeURIComponent(user.id)}`;
  const [pendingRequest, setPendingRequest] = useState<{ requestId: string; action: string } | null>(() => { try { const value = JSON.parse(window.localStorage.getItem(pendingStorage) ?? 'null'); return value && typeof value.requestId === 'string' && typeof value.action === 'string' ? value : null; } catch { return null; } });
  function remember(requestId: string, action: string) { const value = { requestId, action }; try { window.localStorage.setItem(pendingStorage, JSON.stringify(value)); } catch { throw new RemoteRequestError(true); } setPendingRequest(value); }
  function acknowledge() { setPendingRequest(null); try { window.localStorage.removeItem(pendingStorage); } catch { /* No sensitive payload is persisted. */ } }
  async function recover() {
    if (!pendingRequest || lock.current) return; lock.current = true; setBusy(true);
    try {
      if (pendingRequest.action === 'credential_revoke') {
        const receipt = await personalRemoteApi.recoverCredential(pendingRequest.requestId);
        if (receipt.status !== 'revoked') throw new Error('Receipt mismatch'); setCredential(null);
      } else if (pendingRequest.action === 'bind') {
        const receipt = await personalRemoteApi.recoverBinding(pendingRequest.requestId);
        if (receipt.requestId !== pendingRequest.requestId || receipt.action !== 'bind' || receipt.connection.ownerId !== user.id) throw new Error('Receipt mismatch');
      } else {
        const receipt = await personalRemoteApi.recover(pendingRequest.requestId);
        if (receipt.requestId !== pendingRequest.requestId || receipt.action !== `remote.${pendingRequest.action}`) throw new Error('Receipt mismatch');
      }
      acknowledge(); setRefresh(n => n + 1); onChanged(); setNotice('原请求回执已核对。显示当前状态；没有重放验证或绑定。');
    } catch { setNotice('原请求仍未核实。请保留请求标识并联系部署管理员；不会自动创建新请求。'); }
    finally { lock.current = false; setBusy(false); }
  }
  useEffect(() => {
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function read() {
      try {
        const [session, installed, records, custody] = await Promise.all([api.session(controller.signal), personalRemoteApi.providers(controller.signal), personalRemoteApi.list(controller.signal), personalRemoteApi.credentialAvailability(controller.signal).catch(() => ({ enabled: false, providerIds: [] as string[] }))]);
        if (controller.signal.aborted) return;
        if (session.id !== user.id) throw new Error('Identity changed');
        setProviders(installed.filter(p => custody.providerIds.includes(p.providerId) && (!researchSetup || p.providerId === ORX_PERSONAL_PROVIDER))); setRemotes(records.filter(r => !researchSetup || r.providerId === ORX_PERSONAL_PROVIDER)); setVault(custody.enabled === true);
        if (custody.enabled) { const saved = await personalRemoteApi.credentials(controller.signal); if (controller.signal.aborted) return; setCredentials(saved); } else setCredentials([]);
        setReady(true); setError('');
      } catch { if (!controller.signal.aborted) { setReady(false); setError('无法核对个人远程服务配置；操作已禁用。'); } }
      if (!controller.signal.aborted) timer = setTimeout(() => void read(), 5000);
    }
    void read(); return () => { controller.abort(); clearTimeout(timer); };
  }, [user.id, refresh, researchSetup]);
  async function perform(work: () => Promise<void>) {
    if (lock.current || !ready || pendingRequest) return; lock.current = true; setBusy(true); setNotice('');
    try { await work(); setRefresh(n => n + 1); onChanged(); }
    catch (error) { if ((error instanceof RemoteRequestError && error.rejected) || (error instanceof ApiError && definitivelyRejected(error.status))) { acknowledge(); setNotice('请求已明确拒绝。请检查输入、当前权限和部署配置后再试。'); } else setNotice('操作确认未知。请先核对原请求回执，不会自动重试。'); }
    finally { lock.current = false; setBusy(false); }
  }
  const chosenProvider = providers.find(p => p.providerId === providerId);
  const orxProvider = providerId === ORX_PERSONAL_PROVIDER;
  const eligible = (!orxProvider || !!authMode && chosenProvider?.authModes?.includes(authMode)) && ready && !pendingRequest && vault && providers.some(p => p.providerId === providerId) && validOrigin(origin);
  async function configure() {
    if (!eligible || !credential || credential.destination !== origin || credential.providerId !== providerId || !(projectCreation || projectId)) return;
    await perform(async () => {
      const body = { providerId, origin, ...(orxProvider && projectCreation ? { projectCreation: true as const } : { projectId }), credentialRef: credential.credentialRef, credentialRevision: credential.credentialRevision, ...(orxProvider && authMode ? { authMode, ...(!projectCreation && sessionTemplateId.trim() ? { sessionTemplateId: sessionTemplateId.trim() } : {}) } : {}) };
      const key = await keys('personal-remote-configure', { ...body, reference: editing ?? null });
      remember(key.requestId, 'configure'); await personalRemoteApi.configure({ ...body, requestId: key.requestId }, editing); key.acknowledged(); acknowledge();
      setEditing(undefined); setCredential(null); setOrigin(''); setProjectId(''); setNotice('远程配置已保存。下一步手动验证；此操作尚未连接或绑定执行。');
    });
  }
  async function command(remote: PersonalRemote, action: 'verify' | 'revoke' | 'bind') {
    if (!remote.allowedActions.includes(action) || action === 'bind' && !remoteCanBind(remote)) return;
    await perform(async () => {
      const key = await keys(`personal-remote-${action}`, { reference: remote.registrationRef, revision: remote.revision, ...(action === 'bind' ? { taskId, capabilities: remote.capabilities } : {}) });
      remember(key.requestId, action);
      if (action === 'bind') {
        const bound = await api.bindConnection(remote.registrationRef, key.requestId, remote.capabilities, taskId || undefined);
        if (bound.ownerId !== user.id) throw new Error('Invalid owner');
      } else await personalRemoteApi.command(remote, action, key.requestId);
      key.acknowledged(); acknowledge(); setNotice(action === 'verify' ? '验证回执已取得；请查看最新状态，再单独确认绑定。验证不启动任务。' : action === 'bind' ? remote.capabilities.includes('project:create') ? '项目创建连接已绑定。进入 OpenResearch 普通模式，预览输入与副作用并逐次批准。' : [PERSONAL_PROVIDER, ORX_PERSONAL_PROVIDER].includes(remote.providerId) ? '个人会话连接已绑定。下一步在个人远程会话中准备命令、审阅并单独确认启动。' : '只读连接已绑定。此连接没有会话执行权限，不能据此启动远程研究。' : '本地远程访问已撤销；不代表上游进程已停止或远程资源已删除。');
    });
  }
  return <section aria-label="个人远程服务"><h2>连接自己的远程服务</h2>
    {researchSetup ? <p>先保存服务登录凭据、验证并绑定，再按名称选择项目。只读取远端配置；此处不创建项目或调用模型。模型由 OpenResearch 远端账户提供，Factory 模型密钥不会转发。</p> : <><p>保存服务凭据 → 配置目标 → 只读验证 → 绑定，之后可回到 OpenResearch 开始研究。</p><p className="quiet">OpenCode 是可选的外部 runtime。已有只读连接不会自动获得研究执行或项目创建权限。受管完整研究执行仍需单独验证。</p></>}
    {pendingRequest && <p role="alert">待核对原请求 {pendingRequest.requestId}。<button disabled={busy} onClick={() => void recover()}>核对原远程请求</button></p>}
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {ready && (!providers.length || !vault) && <p className="state-note">此部署尚未启用{!providers.length ? '个人远程提供方' : '安全凭据保险库'}。需要部署管理员配置后才能自助连接；下面仍可查看已登记状态。请联系管理员启用 OpenResearch 个人会话提供方、安全凭据保险库与个人命令能力，并确认允许访问你的 HTTPS 服务目标。需要新建项目时，还须单独启用创建应用和创建连接；现有项目绑定不能替代。</p>}
    {ready && !!providers.length && vault && <div className="material-editor"><h3>{editing ? '重新配置远程服务' : '添加个人远程服务'}</h3>
      <fieldset disabled={busy || showCredential || !!credential}><label>提供方<select aria-label="远程提供方" value={providerId} onChange={event => { setProviderId(event.target.value); setAuthMode(''); setSessionTemplateId(''); setProjectCreation(false); }}><option value="">选择提供方</option>{providers.map(p => <option key={p.providerId} value={p.providerId}>{p.providerId === ORX_PERSONAL_PROVIDER ? 'OpenResearch 原生项目与会话' : p.providerId === PERSONAL_PROVIDER ? 'OpenCode 原生会话（可选）' : p.providerId}</option>)}</select></label>
      <label>HTTPS 服务源<input aria-label="HTTPS 服务源" value={origin} placeholder="https://remote.example.org" onChange={event => setOrigin(event.target.value)} /></label>{orxProvider && <label>OpenResearch 认证方式<select aria-label="OpenResearch 认证方式" value={authMode} onChange={event => setAuthMode(event.target.value as '' | 'bearer' | 'basic-proxy')}><option value="">明确选择认证方式</option>{chosenProvider?.authModes?.map(mode => <option key={mode} value={mode}>{mode === 'bearer' ? '已有 OpenResearch 服务令牌' : 'HTTPS 反向代理用户名与密码'}</option>)}</select></label>}</fieldset>
      {orxProvider && chosenProvider?.projectCreationSupported && <label><input type="checkbox" aria-label="用于创建新项目" disabled={busy} checked={projectCreation} onChange={event => setProjectCreation(event.target.checked)} />允许读取项目列表及预览新项目创建（实际创建另行确认，不会自动创建）</label>}
      {!projectCreation && <label>预期项目 ID<input aria-label="预期项目 ID" disabled={busy} value={projectId} onChange={event => setProjectId(event.target.value)} /></label>}
      {orxProvider && !projectCreation && chosenProvider?.sessionTemplateSupported && <label>新会话模板 ID（可选）<input aria-label="新会话模板 ID（可选）" value={sessionTemplateId} disabled={busy} maxLength={160} onChange={event => setSessionTemplateId(event.target.value)} /><small>留空时只关联已有原生会话。填写会启用从已验证模板准备新会话，继续沿用远程模型与工具配置。</small></label>}
      {!credential && !showCredential && <label>已有此目标的凭据<select aria-label="已有此目标的凭据" disabled={!eligible || busy} value="" onChange={event => setCredential(credentials.find(c => c.credentialRef === event.target.value) ?? null)}><option value="">选择已保存凭据（可选）</option>{credentials.filter(c => c.status === 'active' && c.destination === origin && c.providerId === providerId).map(c => <option key={c.credentialRef} value={c.credentialRef}>{c.credentialRef}</option>)}</select></label>}
      {!credential && !showCredential && <button disabled={!eligible || busy} onClick={() => setShowCredential(true)}>输入并保存个人凭据</button>}
      {showCredential && <CredentialForm key={`${providerId}:${origin}:${authMode}`} credentialKind={orxProvider && authMode === 'bearer' ? 'service-token' : 'password'} owner={user.id} providerId={providerId} destination={origin} onSaved={value => { setProviderId(value.providerId); setOrigin(value.destination); setCredential(value); setShowCredential(false); }} onCancel={() => setShowCredential(false)} />}
      {credential && <><p>凭据已安全保存，仅保留不透明引用。配置将使用此目标与凭据版本。</p><button disabled={busy || !eligible || !(projectCreation || projectId)} onClick={() => void configure()}>确认{editing ? '重新配置' : '保存配置'}</button><button disabled={busy} onClick={() => void perform(async () => { const key = await keys('personal-credential-revoke', { ref: credential.credentialRef, revision: credential.credentialRevision }); remember(key.requestId, 'credential_revoke'); await personalRemoteApi.revokeCredential(credential, key.requestId); key.acknowledged(); acknowledge(); setCredential(null); setNotice('已撤销尚未用于配置的凭据。'); })}>撤销此凭据（关联连接将失效）</button></>}
      {editing && <p>重新配置会使旧验证与绑定失效。保存后必须重新验证、绑定和制定计划。</p>}
    </div>}
    {!researchSetup && <label>新绑定的任务范围<select aria-label="个人远程任务范围" disabled={busy || !ready} value={taskId} onChange={event => setTaskId(event.target.value)}><option value="">我的用户范围</option>{jobs.filter(j => !['completed', 'failed', 'canceled'].includes(j.status)).map(job => <option key={job.id} value={job.id}>{job.input.topic}</option>)}</select></label>}
    {remotes.map(remote => <article className="material-row review-row" key={remote.registrationRef}><div className="material-info"><h3>{remote.origin}</h3><p>{statusNames[remote.status] ?? '状态尚未确认'} · {remote.projectId ? `项目 ${remote.projectId}` : '项目创建服务（逐次批准）'}</p><p>验证到期：{remote.expiresAt ? new Date(remote.expiresAt).toLocaleString('zh-CN') : '尚未验证'}</p><p>{remote.capabilities.includes('project:create') ? '项目创建能力' : [PERSONAL_PROVIDER, ORX_PERSONAL_PROVIDER].includes(remote.providerId) ? '个人会话能力' : '只读能力'}：{remote.capabilities.join('、') || '尚未授权'}</p><details><summary>登记与版本</summary>{remote.registrationRef} · {remote.revision}</details>
      <div className="material-actions"><button disabled={busy || !!pendingRequest || !ready || !remote.allowedActions.includes('verify')} onClick={() => void command(remote, 'verify')}>验证远程服务</button><button disabled={busy || !!pendingRequest || !ready || !remoteCanBind(remote)} onClick={() => void command(remote, 'bind')}>{remote.capabilities.includes('project:create') ? '确认绑定项目创建连接' : [PERSONAL_PROVIDER, ORX_PERSONAL_PROVIDER].includes(remote.providerId) ? '确认绑定个人会话连接' : '确认绑定只读连接'}</button>
      <button disabled={busy || !!pendingRequest || !ready || !vault || !!credential || showCredential || !remote.allowedActions.includes('configure')} onClick={() => { setEditing(remote.registrationRef); setProviderId(remote.providerId); setOrigin(remote.origin); setProjectId(remote.projectId); setAuthMode(''); setSessionTemplateId(''); setProjectCreation(!remote.projectId); }}>重新配置</button>
      <button disabled={busy || !!pendingRequest || !ready || !remote.allowedActions.includes('revoke')} onClick={() => void command(remote, 'revoke')}>撤销远程访问</button></div></div></article>)}
    {!researchSetup && <details className="technical-detail"><summary>OpenCode 会话（可选外部 runtime）</summary><p>仅用于你已配置的 OpenCode 服务。无需此连接也可使用独立的 OpenResearch 原生提供方。</p><PersonalAgentSessions key={`${user.id}:${refresh}`} ownerId={user.id} onTask={onTask} /></details>}
  </section>;
}
