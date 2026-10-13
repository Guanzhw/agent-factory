import { useEffect, useRef, useState } from 'react';
import { api } from './api.js';
import { personalRemoteApi, RemoteRequestError, type PersonalCredential } from './personalRemoteApi.js';
import { personalToolConnectionApi, ToolConnectionError, type PersonalToolDescriptor, type PersonalToolConnection } from './personalToolConnectionApi.js';

type Props = { ownerId: string; revision?: number; onChanged: () => void };
type Setup = {
  action: 'setup'; owner: string; requestId: string; adapterId: string; descriptorRevision: string;
  toolName: string; transport: 'cli' | 'mcp'; credentialProviderId: string; credentialDestination: string;
  capabilities: string[]; credentialRequestId: string; bindRequestId: string;
  stage: 'credential' | 'configure' | 'bind'; dispatched: boolean;
  credential?: PersonalCredential; registrationRef?: string;
};
type Revoke = { action: 'revoke'; owner: string; requestId: string; registrationRef: string; dispatched: boolean };
type Command = Setup | Revoke;
const identifier = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_.:@-]{1,200}$/.test(value);
const statusNames: Record<string, string> = { configured: '配置可用', revoked: '已撤销', unavailable: '当前不可用', credential_unavailable: '凭据不可用', adapter_changed: '工具版本已变化' };

function credential(value: PersonalCredential): PersonalCredential {
  if (!value || ![value.credentialRef, value.credentialRevision, value.providerId].every(identifier)
      || typeof value.destination !== 'string' || !value.destination || value.destination.length > 1000
      || Object.keys(value).some(k => !['credentialRef', 'credentialRevision', 'providerId', 'destination', 'status'].includes(k))
      || !['active', 'revoked'].includes(value.status)) throw new Error('Invalid credential metadata');
  return { credentialRef: value.credentialRef, credentialRevision: value.credentialRevision, providerId: value.providerId, destination: value.destination, status: value.status };
}
/** Only public scope and original request identifiers may survive a refresh. */
export function readToolCommand(raw: string | null, owner: string): Command | null {
  try {
    const value = JSON.parse(raw ?? 'null') as Command;
    if (!value || value.owner !== owner || !identifier(value.requestId) || typeof value.dispatched !== 'boolean') return null;
    if (value.action === 'revoke') return identifier(value.registrationRef)
      && Object.keys(value).every(k => ['action', 'owner', 'requestId', 'registrationRef', 'dispatched'].includes(k))
      ? { action: 'revoke', owner, requestId: value.requestId, registrationRef: value.registrationRef, dispatched: value.dispatched } : null;
    if (value.action !== 'setup' || !['credential', 'configure', 'bind'].includes(value.stage)
        || !['cli', 'mcp'].includes(value.transport)
        || ![value.adapterId, value.descriptorRevision, value.toolName, value.credentialProviderId, value.credentialRequestId, value.bindRequestId].every(identifier)
        || typeof value.credentialDestination !== 'string' || !value.credentialDestination || value.credentialDestination.length > 1000
        || !Array.isArray(value.capabilities) || !value.capabilities.every(identifier)
        || value.registrationRef !== undefined && !identifier(value.registrationRef)
        || Object.keys(value).some(k => !['action', 'owner', 'requestId', 'adapterId', 'descriptorRevision', 'toolName', 'transport', 'credentialProviderId', 'credentialDestination', 'capabilities', 'credentialRequestId', 'bindRequestId', 'stage', 'dispatched', 'credential', 'registrationRef'].includes(k))) return null;
    const saved = value.credential ? credential(value.credential) : undefined;
    if (saved && (saved.providerId !== value.credentialProviderId || saved.destination !== value.credentialDestination || saved.status !== 'active')
        || value.stage !== 'credential' && !saved || value.stage === 'bind' && !value.registrationRef) return null;
    return { action: 'setup', owner, requestId: value.requestId, adapterId: value.adapterId, descriptorRevision: value.descriptorRevision,
      toolName: value.toolName, transport: value.transport, credentialProviderId: value.credentialProviderId, credentialDestination: value.credentialDestination,
      capabilities: [...value.capabilities], credentialRequestId: value.credentialRequestId, bindRequestId: value.bindRequestId,
      stage: value.stage, dispatched: value.dispatched, ...(saved ? { credential: saved } : {}), ...(value.registrationRef ? { registrationRef: value.registrationRef } : {}) };
  } catch { return null; }
}

export function PersonalToolConnections(props: Props) { return <ToolConnections key={props.ownerId} {...props}/>; }
function ToolConnections({ ownerId, revision = 0, onChanged }: Props) {
  const storage = `factory-personal-tool-command:${encodeURIComponent(ownerId)}`;
  const [pending, setPending] = useState<Command | null>(() => { try { return readToolCommand(localStorage.getItem(storage), ownerId); } catch { return null; } });
  const [descriptors, setDescriptors] = useState<PersonalToolDescriptor[]>([]);
  const [records, setRecords] = useState<PersonalToolConnection[]>([]);
  const [credentials, setCredentials] = useState<PersonalCredential[]>([]);
  const [providers, setProviders] = useState<string[]>([]);
  const [adapterId, setAdapterId] = useState(''); const [credentialRef, setCredentialRef] = useState('');
  const [source, setSource] = useState<'saved' | 'new'>('saved'); const [token, setToken] = useState(''); const [consent, setConsent] = useState(false);
  const [ready, setReady] = useState(false); const [busy, setBusy] = useState(false); const [blocked, setBlocked] = useState(false);
  const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [refresh, setRefresh] = useState(0);
  const alive = useRef(true); const lock = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  function accountChanged() {
    setToken(''); setConsent(false); setCredentialRef(''); setAdapterId(''); setCredentials([]); setDescriptors([]); setRecords([]); setPending(null);
    setReady(false); setBlocked(true); setError('当前登录账户已改变。已清空输入，请刷新后管理自己的工具连接。');
  }
  async function verifyOwner() {
    const current = await api.session();
    if (!alive.current) throw new Error('Unmounted');
    if (current.id !== ownerId) { accountChanged(); throw new ToolConnectionError(403, 'EXPECTED_OWNER_MISMATCH'); }
  }
  useEffect(() => {
    const controller = new AbortController(); setReady(false);
    void (async () => {
      await verifyOwner();
      const [installed, tools] = await Promise.all([personalToolConnectionApi.descriptors(ownerId, controller.signal), personalToolConnectionApi.list(ownerId, controller.signal)]);
      const available = installed.length ? await personalRemoteApi.credentialAvailability(controller.signal) : { enabled: false, providerIds: [] };
      const saved = available.enabled ? (await personalRemoteApi.credentials(controller.signal, ownerId)).map(credential) : [];
      if (!controller.signal.aborted && alive.current) {
        setDescriptors(installed); setRecords(tools); setCredentials(saved); setProviders(available.enabled ? available.providerIds : []);
        setReady(true); setError('');
      }
    })().catch(failure => { if (!controller.signal.aborted && alive.current) {
      if ((failure instanceof ToolConnectionError || failure instanceof RemoteRequestError) && failure.code === 'EXPECTED_OWNER_MISMATCH') accountChanged();
      else setError('暂时无法读取工具连接。请重新读取；原请求和连接保留。');
    } });
    return () => controller.abort();
  }, [ownerId, revision, refresh]);
  const descriptor = descriptors.find(d => d.adapterId === adapterId);
  const matching = credentials.filter(c => c.status === 'active' && c.providerId === descriptor?.credentialProviderId && c.destination === descriptor?.credentialDestination);
  const selected = matching.find(c => c.credentialRef === credentialRef);
  function retain(command: Command, begin = false) {
    const safe = readToolCommand(JSON.stringify(command), ownerId);
    if (!safe) throw new Error('Invalid command');
    const raw = localStorage.getItem(storage); const previous = readToolCommand(raw, ownerId);
    if (raw && !previous || previous && previous.requestId !== command.requestId || !begin && previous?.requestId !== command.requestId) throw new Error('Original command changed');
    if (!begin && previous?.action === 'setup' && command.action === 'setup') {
      const stages = ['credential', 'configure', 'bind'];
      if (stages.indexOf(previous.stage) > stages.indexOf(command.stage)
          || previous.stage === command.stage && previous.dispatched) throw new Error('Original step already dispatched');
    }
    if (!begin && previous?.action === 'revoke' && previous.dispatched) throw new Error('Original revocation already dispatched');
    localStorage.setItem(storage, JSON.stringify(safe)); setPending(safe); return safe;
  }
  function retainSetup(command: Setup, begin = false) { return retain(command, begin) as Setup; }
  function release(command: Command) {
    if (readToolCommand(localStorage.getItem(storage), ownerId)?.requestId !== command.requestId) throw new Error('Original command changed');
    localStorage.removeItem(storage); setPending(null);
  }
  function changed() { setRefresh(n => n + 1); onChanged(); }
  function acceptedCredential(value: PersonalCredential, s: Setup) {
    const c = credential(value);
    if (c.providerId !== s.credentialProviderId || c.destination !== s.credentialDestination || c.status !== 'active') throw new Error('Credential scope changed');
    return c;
  }
  function matchTool(tool: PersonalToolConnection, s: Setup) {
    if (tool.adapterId !== s.adapterId || tool.descriptorRevision !== s.descriptorRevision || tool.toolName !== s.toolName || tool.transport !== s.transport
        || tool.credentialRef !== s.credential?.credentialRef || tool.credentialRevision !== s.credential?.credentialRevision
        || s.registrationRef && tool.registrationRef !== s.registrationRef
        || tool.capabilities.length !== s.capabilities.length || s.capabilities.some(c => !tool.capabilities.includes(c))) throw new Error('Tool binding scope changed');
  }
  async function post<T>(command: Command, write: () => Promise<T>): Promise<T> {
    await verifyOwner();
    // A failed identity check or unmount is still a known unsent step. Mark it
    // only immediately before calling the write, after all async preflight.
    if (!alive.current) throw new Error('Unmounted');
    retain({ ...command, dispatched: true });
    try { return await write(); }
    catch (failure) {
      // Only a direct, explicit rejection settles this dispatch. A failed GET
      // of its original receipt (even 404) can never authorize another POST.
      if (alive.current && (failure instanceof RemoteRequestError && failure.rejected
          || failure instanceof ToolConnectionError && [400, 401, 403, 404, 405, 413, 415, 422].includes(failure.status))) release(command);
      throw failure;
    }
  }
  async function continueSetup(original: Setup) {
    let s = original;
    if (s.stage === 'credential') {
      if (!s.dispatched) { release(s); setNotice('原凭据步骤尚未发送。请重新输入令牌并明确保存；没有提交或重发原凭据。'); return; }
      const value = await personalRemoteApi.recoverCredential(s.credentialRequestId, ownerId);
      if (!alive.current) return;
      s = retainSetup({ ...s, credential: acceptedCredential(value, s), stage: 'configure', dispatched: false });
    }
    if (s.stage === 'configure') {
      let tool: PersonalToolConnection;
      if (s.dispatched) {
        const receipt = await personalToolConnectionApi.recover(ownerId, s.requestId);
        if (receipt.action !== 'tool.configure') throw new Error('Original action changed');
        tool = receipt.tool;
      } else {
        tool = await post(s, () => personalToolConnectionApi.configure(ownerId, { adapterId: s.adapterId,
          credentialRef: s.credential!.credentialRef, credentialRevision: s.credential!.credentialRevision, requestId: s.requestId }));
      }
      if (!alive.current) return;
      matchTool(tool, s);
      if (!tool.available || tool.status !== 'configured' || !tool.allowedActions.includes('bind')) {
        release(s); changed(); setNotice('原工具保存已核对，但配置当前不可用或已撤销。没有继续绑定，也不会替换凭据。'); return;
      }
      s = retainSetup({ ...s, registrationRef: tool.registrationRef, stage: 'bind', dispatched: false });
    }
    let connection;
    if (s.dispatched) {
      const receipt = await personalToolConnectionApi.recoverBinding(ownerId, s.bindRequestId);
      if (receipt.action !== 'bind') throw new Error('Original binding action changed');
      connection = receipt.connection;
    } else {
      // Recheck the installed descriptor and credential availability after any
      // interrupted earlier phase. Never choose another account or credential.
      const installed = await personalToolConnectionApi.descriptors(ownerId);
      if (!alive.current) return;
      const current = installed.find(d => d.adapterId === s.adapterId);
      if (!current || current.revision !== s.descriptorRevision || current.credentialProviderId !== s.credentialProviderId || current.credentialDestination !== s.credentialDestination) throw new Error('Installed tool changed');
      connection = await post(s, () => personalToolConnectionApi.bind(ownerId, s.registrationRef!, s.bindRequestId, s.capabilities));
    }
    if (!alive.current) return;
    if (connection.ownerId !== ownerId || connection.registrationRef !== s.registrationRef || connection.kind !== 'tool'
        || connection.taskId !== null
        || connection.capabilities.length !== s.capabilities.length || s.capabilities.some(c => !connection.capabilities.includes(c))) throw new Error('Connection scope changed');
    if (connection.status !== 'active' || !connection.available) {
      release(s); changed(); setNotice('原连接绑定已核对，但连接当前不可用或已撤销。没有重新绑定或改用其他凭据。'); return;
    }
    release(s); setToken(''); setConsent(false); setCredentialRef(''); changed();
    setNotice('工具已保存并绑定到你的连接。应用可按声明使用此连接；保存没有执行工具或验证第三方服务。');
  }
  async function run(work: () => Promise<void>) {
    if (lock.current || blocked) return; lock.current = true; setBusy(true); setError(''); setNotice('');
    try { await verifyOwner(); await work(); }
    catch (failure) {
      if (alive.current) {
        setToken(''); setConsent(false);
        if ((failure instanceof RemoteRequestError || failure instanceof ToolConnectionError) && failure.code === 'EXPECTED_OWNER_MISMATCH') accountChanged();
        else setError('操作尚未确认。请核对原请求或重新读取；不会重复发送，也不会改用其他账户的凭据。');
      }
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  function save() {
    if (!ready || pending || !descriptor || source === 'saved' && !selected || source === 'new' && (!token || !consent || !providers.includes(descriptor.credentialProviderId))) return;
    void run(async () => {
      const s = retainSetup({ action: 'setup', owner: ownerId, requestId: crypto.randomUUID(), adapterId: descriptor.adapterId, descriptorRevision: descriptor.revision,
        toolName: descriptor.toolName, transport: descriptor.transport, credentialProviderId: descriptor.credentialProviderId, credentialDestination: descriptor.credentialDestination,
        capabilities: [...descriptor.capabilities], credentialRequestId: crypto.randomUUID(), bindRequestId: crypto.randomUUID(),
        stage: source === 'new' ? 'credential' : 'configure', dispatched: false, ...(selected && source === 'saved' ? { credential: selected } : {}) }, true);
      if (s.credential) { await continueSetup(s); return; }
      const secret = token; setToken(''); setConsent(false);
      const value = await post(s, () => personalRemoteApi.saveCredential({ providerId: s.credentialProviderId, destination: s.credentialDestination, username: 'bearer', password: secret, requestId: s.credentialRequestId }, ownerId));
      if (alive.current) await continueSetup(retainSetup({ ...s, credential: acceptedCredential(value, s), stage: 'configure', dispatched: false }));
    });
  }
  function revoke(record: PersonalToolConnection) {
    if (pending || !ready || !record.allowedActions.includes('revoke')) return;
    void run(async () => {
      const command = retain({ action: 'revoke', owner: ownerId, requestId: crypto.randomUUID(), registrationRef: record.registrationRef, dispatched: false }, true) as Revoke;
      const value = await post(command, () => personalToolConnectionApi.revoke(ownerId, record.registrationRef, command.requestId));
      if (!alive.current) return;
      if (value.registrationRef !== command.registrationRef || value.status !== 'revoked' || value.available) throw new Error('Revoke unconfirmed');
      release(command); changed(); setNotice('工具配置已撤销。后续调用不能继续使用此配置；原任务与产物保留。');
    });
  }
  function recover() {
    if (!pending) return;
    const original = pending;
    void run(async () => {
      if (original.action === 'setup') { await continueSetup(original); return; }
      if (!original.dispatched) { release(original); setNotice('原撤销步骤尚未发送。需要撤销时请重新选择；没有提交或重发撤销。'); return; }
      const receipt = await personalToolConnectionApi.recover(ownerId, original.requestId);
      if (!alive.current) return;
      if (receipt.action !== 'tool.revoke' || receipt.tool.registrationRef !== original.registrationRef || receipt.tool.status !== 'revoked' || receipt.tool.available) throw new Error('Revoke unconfirmed');
      release(original); changed(); setNotice('原撤销已核对；没有重发撤销请求。');
    });
  }
  const disabled = busy || blocked || !ready || !!pending;
  const canSave = !!descriptor && (source === 'saved' ? !!selected : !!token && consent && providers.includes(descriptor.credentialProviderId));
  return <section aria-labelledby="personal-tools-title"><h2 id="personal-tools-title">我的工具连接</h2>
    <p>选择已安装的 CLI 或 MCP 工具，并绑定你自己的凭据。应用只在声明了此工具和连接时使用；这里不会执行工具。</p>
    <button className="secondary" disabled={busy || blocked} onClick={() => setRefresh(n => n + 1)}>重新读取工具连接</button>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {pending && <aside className="state-note"><p>原工具{pending.action === 'revoke' ? '撤销' : '保存或绑定'}尚待核对。仅恢复原请求，已发送的步骤不会重发。</p><button disabled={busy || blocked} onClick={recover}>核对原工具请求</button></aside>}
    {!ready ? <p className="quiet">正在读取已安装工具与本人连接。</p> : !descriptors.length ? <p className="list-empty">此部署尚未安装个人 CLI/MCP 工具。安装后可在这里绑定自己的凭据；无需添加凭据或提交审批。</p> : <form className="material-editor" aria-label="添加个人工具连接" onSubmit={event => { event.preventDefault(); save(); }}>
      <fieldset disabled={disabled}><label>工具<select aria-label="个人工具" value={adapterId} onChange={event => { setAdapterId(event.target.value); setCredentialRef(''); setToken(''); setConsent(false); }}><option value="">选择已安装工具</option>{descriptors.map(d => <option key={d.adapterId} value={d.adapterId}>{d.toolName} · {d.transport.toUpperCase()}</option>)}</select></label>
        {descriptor && <><p>{descriptor.description}</p>{descriptor.transport === 'cli' && <p className="quiet">CLI 在部署服务器上运行；当前适配器支持 Linux/POSIX 服务器，Windows 浏览器可管理连接。</p>}<dl className="plan-details"><dt>凭据用途</dt><dd>{descriptor.credentialProviderId}</dd><dt>固定服务目标</dt><dd>{descriptor.credentialDestination}</dd><dt>允许能力</dt><dd>{descriptor.capabilities.join('、')}</dd></dl>
          <label>凭据来源<select aria-label="工具凭据来源" value={source} onChange={event => { setSource(event.target.value as 'saved' | 'new'); setToken(''); setConsent(false); }}><option value="saved">使用本人已保存的凭据</option><option value="new" disabled={!providers.includes(descriptor.credentialProviderId)}>安全保存新令牌</option></select></label>
          {source === 'saved' ? <><label>本人凭据<select aria-label="工具已有凭据" value={credentialRef} onChange={event => setCredentialRef(event.target.value)}><option value="">选择此用途与目标的凭据</option>{matching.map(c => <option key={c.credentialRef} value={c.credentialRef}>{c.credentialRef} · {c.credentialRevision}</option>)}</select></label>{!matching.length && <p className="quiet">没有与此工具用途及目标匹配的本人凭据。不会使用服务器或其他账户的凭据。</p>}</>
            : <><label>工具访问令牌<input aria-label="工具访问令牌" type="password" autoComplete="new-password" value={token} onChange={event => setToken(event.target.value)}/></label><label><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)}/>我同意将令牌加密保存到凭据保险库，仅供上述工具用途和固定目标使用。</label></>}
        </>}
        <button className="primary" disabled={!canSave}>保存并绑定工具</button>
      </fieldset>
    </form>}
    {records.map(record => <article className="material-row review-row" key={record.registrationRef}><div className="material-info"><h3>{record.toolName} · {record.transport.toUpperCase()}</h3><p>{statusNames[record.status] ?? '状态待核对'}</p><p className="quiet">配置状态不代表第三方服务或命令已经验证。</p><details className="technical-detail"><summary>工具配置引用</summary><span>{record.registrationRef}</span><span>版本 {record.revision}</span><span>能力 {record.capabilities.join('、')}</span></details></div><button className="secondary danger" disabled={disabled || !record.allowedActions.includes('revoke')} onClick={() => revoke(record)}>{record.status === 'revoked' ? '工具已撤销' : '撤销工具配置'}</button></article>)}
  </section>;
}
