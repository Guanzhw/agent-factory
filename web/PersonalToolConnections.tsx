import { ReusableToolOperations } from './ReusableToolOperations.js';
import { useEffect, useRef, useState } from 'react';
import { api } from './api.js';
import { personalRemoteApi, RemoteRequestError, type PersonalCredential } from './personalRemoteApi.js';
import { personalToolConnectionApi, ToolConnectionError, type DiscoveredTool, type MemberToolConfiguration, type PersonalToolDescriptor, type PersonalToolConnection } from './personalToolConnectionApi.js';

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
      const available = await personalRemoteApi.credentialAvailability(controller.signal);
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
  const installedDescriptors = descriptors.filter(value => !value.adapterId.startsWith('member-tool-'));
  const descriptor = installedDescriptors.find(d => d.adapterId === adapterId);
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
      if (!current || current.revision !== s.descriptorRevision || current.credentialProviderId !== s.credentialProviderId || current.credentialDestination !== s.credentialDestination) {
        setError('已安装工具已变化或移除，绑定尚未发送。可以结束未发送步骤；已保存的工具配置保留。'); return;
      }
      try { connection = await post(s, () => personalToolConnectionApi.bind(ownerId, s.registrationRef!, s.bindRequestId, s.capabilities)); }
      catch (failure) {
        // Only these direct bind POST responses prove that its precondition
        // failed before a binding/receipt was written. Never apply this to GET
        // recovery, unknown conflicts or an invalid/missing success response.
        if (alive.current && failure instanceof ToolConnectionError && failure.status === 409
            && ['PERSONAL_TOOL_CREDENTIAL_UNAVAILABLE', 'PERSONAL_TOOL_REVOKED', 'PERSONAL_TOOL_ADAPTER_UNAVAILABLE', 'PERSONAL_TOOL_ADAPTER_CHANGED'].includes(failure.code ?? '')) {
          release(s); setToken(''); setConsent(false); setCredentialRef(''); changed();
          setNotice('绑定请求已被明确拒绝。已保存的工具配置和原保存回执保留；没有重发绑定或更换凭据。'); return;
        }
        throw failure;
      }
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
  function endUnsent() {
    if (!pending || pending.dispatched) return;
    const original = pending;
    void run(async () => {
      // Another tab may have sent or advanced this command while the owner
      // check was pending. Only the same still-unsent step can be discarded.
      const current = readToolCommand(localStorage.getItem(storage), ownerId);
      if (!current || current.requestId !== original.requestId || current.action !== original.action || current.dispatched
          || current.action === 'setup' && original.action === 'setup' && current.stage !== original.stage) throw new Error('Original step changed');
      release(original); setToken(''); setConsent(false); setCredentialRef(''); changed();
      setNotice('已结束未发送步骤。已保存的工具配置和原保存回执保留；没有发送或重发请求。');
    });
  }
  const disabled = busy || blocked || !ready || !!pending;
  const canSave = !!descriptor && (source === 'saved' ? !!selected : !!token && consent && providers.includes(descriptor.credentialProviderId));
  return <section aria-labelledby="personal-tools-title"><h2 id="personal-tools-title">我的工具连接</h2>
    <p>连接自己的 MCP 服务或服务器上的 CLI 命令，保存后可用于组件与工作流。</p>
    <ReusableToolOperations ownerId={ownerId} credentials={credentials} disabled={disabled} onChanged={changed}/>
    <MemberToolSetup ownerId={ownerId} credentials={credentials} providers={providers} disabled={disabled} onChanged={changed}/>
    <button className="secondary" disabled={busy || blocked} onClick={() => setRefresh(n => n + 1)}>重新读取工具连接</button>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {pending && <aside className="state-note"><p>原工具{pending.action === 'revoke' ? '撤销' : '保存或绑定'}尚待核对。仅恢复原请求，已发送的步骤不会重发。</p><button disabled={busy || blocked} onClick={recover}>核对原工具请求</button>{!pending.dispatched && <button className="secondary" disabled={busy || blocked} onClick={endUnsent}>结束未发送步骤</button>}</aside>}
    {!ready ? <p className="quiet">正在读取工具与本人连接。</p> : !!installedDescriptors.length && <form className="material-editor" aria-label="添加个人工具连接" onSubmit={event => { event.preventDefault(); save(); }}>
      <fieldset disabled={disabled}><label>工具<select aria-label="个人工具" value={adapterId} onChange={event => { setAdapterId(event.target.value); setCredentialRef(''); setToken(''); setConsent(false); }}><option value="">选择已安装工具</option>{installedDescriptors.map(d => <option key={d.adapterId} value={d.adapterId}>{d.toolName} · {d.transport.toUpperCase()}</option>)}</select></label>
        {descriptor && <><p>{descriptor.description}</p>{descriptor.transport === 'cli' && <p className="quiet">CLI 在部署服务器上运行；当前适配器支持 Linux/POSIX 服务器，Windows 浏览器可管理连接。</p>}<dl className="plan-details"><dt>凭据用途</dt><dd>{descriptor.credentialProviderId}</dd><dt>固定服务目标</dt><dd>{descriptor.credentialDestination}</dd><dt>允许能力</dt><dd>{descriptor.capabilities.join('、')}</dd></dl>
          <label>凭据来源<select aria-label="工具凭据来源" value={source} onChange={event => { setSource(event.target.value as 'saved' | 'new'); setToken(''); setConsent(false); }}><option value="saved">使用本人已保存的凭据</option><option value="new" disabled={!providers.includes(descriptor.credentialProviderId)}>安全保存新令牌</option></select></label>
          {source === 'saved' ? <><label>本人凭据<select aria-label="工具已有凭据" value={credentialRef} onChange={event => setCredentialRef(event.target.value)}><option value="">选择此用途与目标的凭据</option>{matching.map(c => <option key={c.credentialRef} value={c.credentialRef}>{c.credentialRef} · {c.credentialRevision}</option>)}</select></label>{!matching.length && <p className="quiet">没有与此工具用途及目标匹配的本人凭据。不会使用服务器或其他账户的凭据。</p>}</>
            : <><label>工具访问令牌<input aria-label="工具访问令牌" type="password" autoComplete="new-password" value={token} onChange={event => setToken(event.target.value)}/></label><label><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)}/>我同意将令牌加密保存到凭据保险库，仅供上述工具用途和固定目标使用。</label></>}
        </>}
        <button className="primary" disabled={!canSave}>保存并绑定工具</button>
      </fieldset>
    </form>}
    {records.map(record => <article className="material-row review-row" key={record.registrationRef}><div className="material-info"><h3>{record.toolName} · {record.transport.toUpperCase()}</h3><p>{statusNames[record.status] ?? '状态待核对'} · {record.visibility === 'team' ? '团队共享' : '个人'}{!record.isOwner && ` · ${record.ownerId}`}</p><details className="technical-detail"><summary>组件运行声明</summary><span>{record.registrationRef}</span><pre>{JSON.stringify(record.runtimeBinding, null, 2)}</pre><span>能力 {record.capabilities.join('、')}</span></details></div><ToolResourceActions ownerId={ownerId} record={record} disabled={disabled} onChanged={changed}/>{record.isOwner && <button className="secondary danger" disabled={disabled || !record.allowedActions.includes('revoke')} onClick={() => revoke(record)}>{record.status === 'revoked' ? '工具已撤销' : '撤销工具配置'}</button>}</article>)}
  </section>;
}

type ResourceRequest = { owner: string; requestId: string; bindRequestId: string; stage: 'credential' | 'configure' | 'bind'; registrationRef?: string; capabilities?: string[] };
export function readResourceToolRequest(raw: string | null, owner: string): ResourceRequest | null {
  try {
    const value = JSON.parse(raw ?? 'null') as ResourceRequest;
    if (!value || value.owner !== owner || !identifier(value.requestId) || !identifier(value.bindRequestId)
        || !['credential', 'configure', 'bind'].includes(value.stage)
        || Object.keys(value).some(key => !['owner', 'requestId', 'bindRequestId', 'stage', 'registrationRef', 'capabilities'].includes(key))
        || value.stage === 'bind' && (!identifier(value.registrationRef) || !Array.isArray(value.capabilities) || !value.capabilities.every(identifier))) return null;
    return value;
  } catch { return null; }
}

function MemberToolSetup({ ownerId, credentials, providers, disabled, onChanged }: {
  ownerId: string; credentials: PersonalCredential[]; providers: string[]; disabled: boolean; onChanged: () => void;
}) {
  const storage = `factory-member-tool-request:${encodeURIComponent(ownerId)}`;
  const [pending, setPending] = useState(() => readResourceToolRequest(localStorage.getItem(storage), ownerId));
  const [transport, setTransport] = useState<'mcp' | 'cli'>('mcp');
  const [url, setUrl] = useState(''); const [executable, setExecutable] = useState(''); const [argumentsJson, setArguments] = useState('[]');
  const [workdir, setWorkdir] = useState(''); const [environment, setEnvironment] = useState('{}');
  const [schema, setSchema] = useState('{"type":"object","properties":{}}'); const [toolName, setToolName] = useState('');
  const [credentialRef, setCredentialRef] = useState(''); const [token, setToken] = useState('');
  const [credentialVariable, setCredentialVariable] = useState('API_KEY'); const [outputFormat, setOutputFormat] = useState<'json' | 'text'>('json');
  const [tools, setTools] = useState<DiscoveredTool[]>([]); const [remoteName, setRemoteName] = useState('');
  const [busy, setBusy] = useState(false); const [message, setMessage] = useState('');
  const lock = useRef(false); const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const provider = `member-${transport}`;
  const destination = transport === 'mcp' ? (() => { try { return new URL(url).toString(); } catch { return url; } })() : executable;
  const matching = credentials.filter(value => value.status === 'active' && value.providerId === provider && value.destination === destination);
  const selected = matching.find(value => value.credentialRef === credentialRef);
  function retain(value: ResourceRequest | null) {
    if (value) localStorage.setItem(storage, JSON.stringify(value)); else localStorage.removeItem(storage);
    if (alive.current) setPending(value);
  }
  async function run(operation: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setMessage('');
    try {
      if ((await api.session()).id !== ownerId) throw new ToolConnectionError(403, 'EXPECTED_OWNER_MISMATCH');
      await operation();
    } catch (error) {
      if (alive.current) {
        setToken('');
        const rejected = error instanceof ToolConnectionError && [400, 401, 403, 404, 422].includes(error.status)
          || error instanceof RemoteRequestError && error.rejected;
        if (rejected && !pending) retain(null);
        setMessage(rejected && !pending ? '配置未被接受，请检查输入。' : '请求尚待核对，请恢复原请求。');
      }
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  async function bind(tool: PersonalToolConnection, request: ResourceRequest) {
    if (!alive.current) return;
    if ((await api.session()).id !== ownerId || !alive.current) throw new ToolConnectionError(403, 'EXPECTED_OWNER_MISMATCH');
    if (!tool.available) { retain(null); onChanged(); setMessage('工具配置已保存，当前不可用。'); return; }
    const next: ResourceRequest = { ...request, stage: 'bind', registrationRef: tool.registrationRef, capabilities: tool.capabilities };
    retain(next);
    await personalToolConnectionApi.bind(ownerId, tool.registrationRef, request.bindRequestId, tool.capabilities);
    retain(null); onChanged(); if (alive.current) setMessage('工具已保存并绑定，可用于组件与工作流。');
  }
  function save() {
    void run(async () => {
      const request: ResourceRequest = { owner: ownerId, requestId: crypto.randomUUID(), bindRequestId: crypto.randomUUID(), stage: 'configure' };
      const tool = tools.find(value => value.name === remoteName);
      const config: MemberToolConfiguration = { transport, toolName, description: tool?.description || toolName,
        inputSchema: transport === 'mcp' ? tool!.inputSchema : JSON.parse(schema) as Record<string, unknown>,
        requestId: request.requestId, ...(selected ? { credentialRef: selected.credentialRef, credentialRevision: selected.credentialRevision } : {}),
        ...(transport === 'mcp' ? { url, remoteToolName: remoteName, readOnly: tool?.readOnly } : {
          executable, arguments: JSON.parse(argumentsJson) as string[], ...(workdir ? { workingDirectory: workdir } : {}),
          environment: JSON.parse(environment) as Record<string, string>, stdinJson: true, outputFormat,
          ...(selected ? { credentialEnvironmentVariable: credentialVariable } : {}) }) };
      retain(request);
      await bind(await personalToolConnectionApi.configureResource(ownerId, config), request);
    });
  }
  function recover() {
    if (!pending) return;
    const request = pending;
    void run(async () => {
      if (request.stage === 'credential') {
        await personalRemoteApi.recoverCredential(request.requestId, ownerId);
        retain(null); onChanged(); setMessage('原凭据保存已核对，请选择已保存的凭据继续。');
      } else if (request.stage === 'configure') {
        const receipt = await personalToolConnectionApi.recover(ownerId, request.requestId);
        if (receipt.action !== 'tool.configure') throw new Error('Unexpected receipt');
        await bind(receipt.tool, request);
      } else {
        await personalToolConnectionApi.recoverBinding(ownerId, request.bindRequestId);
        retain(null); onChanged(); setMessage('原工具绑定已核对。');
      }
    });
  }
  const blocked = disabled || busy || !!pending;
  return <form className="material-editor" aria-label="连接自定义工具" onSubmit={event => { event.preventDefault(); save(); }}>
    <h3>连接自己的工具</h3>
    {message && <p role="status">{message}</p>}
    {pending && <button type="button" disabled={busy || disabled} onClick={recover}>恢复原资源请求</button>}
    <fieldset disabled={blocked}>
      <label>连接类型<select aria-label="自定义工具类型" value={transport} onChange={event => { setTransport(event.target.value as 'cli' | 'mcp'); setCredentialRef(''); setTools([]); setToken(''); }}><option value="mcp">MCP 服务</option><option value="cli">CLI 命令</option></select></label>
      {transport === 'mcp' ? <label>MCP URL<input aria-label="MCP URL" placeholder="http://localhost:8000/mcp" value={url} onChange={event => { setUrl(event.target.value); setTools([]); setCredentialRef(''); }}/></label> : <>
        <p className="quiet">CLI 在部署服务器上运行。输入服务器上的可执行文件与工作目录；调用参数作为 JSON 传入 stdin。</p>
        <label>可执行文件<input aria-label="CLI 可执行文件" value={executable} onChange={event => setExecutable(event.target.value)} placeholder="/usr/bin/python3"/></label>
        <label>命令参数（JSON 数组）<textarea aria-label="CLI 命令参数" value={argumentsJson} onChange={event => setArguments(event.target.value)}/></label>
        <label>工作目录<input aria-label="CLI 工作目录" value={workdir} onChange={event => setWorkdir(event.target.value)}/></label>
        <label>用户配置环境变量（JSON）<textarea aria-label="CLI 用户配置" value={environment} onChange={event => setEnvironment(event.target.value)}/></label>
        <label>输入 JSON Schema<textarea aria-label="CLI 输入 Schema" value={schema} onChange={event => setSchema(event.target.value)}/></label>
        <label>输出格式<select aria-label="CLI 输出格式" value={outputFormat} onChange={event => setOutputFormat(event.target.value as 'json' | 'text')}><option value="json">JSON</option><option value="text">文本</option></select></label>
      </>}
      <label>访问凭据<select aria-label="自定义工具凭据" value={credentialRef} onChange={event => setCredentialRef(event.target.value)}><option value="">无需凭据</option>{matching.map(value => <option key={value.credentialRef} value={value.credentialRef}>{value.credentialRef}</option>)}</select></label>
      {transport === 'cli' && selected && <label>凭据环境变量<input value={credentialVariable} onChange={event => setCredentialVariable(event.target.value)}/></label>}
      {providers.includes(provider) && <><label>新访问令牌<input aria-label="自定义工具令牌" type="password" autoComplete="new-password" value={token} onChange={event => setToken(event.target.value)}/></label><button type="button" disabled={!token || !destination} onClick={() => { void run(async () => {
        const secret = token; setToken('');
        const request: ResourceRequest = { owner: ownerId, requestId: crypto.randomUUID(), bindRequestId: crypto.randomUUID(), stage: 'credential' };
        retain(request);
        const saved = await personalRemoteApi.saveCredential({ providerId: provider, destination, username: 'bearer', password: secret, requestId: request.requestId }, ownerId);
        retain(null); setCredentialRef(saved.credentialRef); onChanged(); setMessage('凭据已加密保存。');
      }); }}>加密保存令牌</button></>}
      {transport === 'mcp' && <><button type="button" disabled={!url} onClick={() => { void run(async () => {
        const result = await personalToolConnectionApi.discover(ownerId, url, selected);
        setUrl(result.url); setTools(result.tools); setRemoteName(''); setMessage(`已发现 ${result.tools.length} 个工具。`);
      }); }}>发现 MCP 工具</button><label>MCP 工具<select aria-label="发现的 MCP 工具" value={remoteName} onChange={event => { setRemoteName(event.target.value); setToolName(event.target.value.replace(/[^A-Za-z0-9_]/g, '_').replace(/^[^A-Za-z_]/, '_').slice(0, 64)); }}><option value="">选择工具</option>{tools.map(tool => <option key={tool.name} value={tool.name}>{tool.name}</option>)}</select></label></>}
      <label>调用名称<input aria-label="自定义工具调用名称" value={toolName} onChange={event => setToolName(event.target.value)} pattern={'[A-Za-z_][A-Za-z0-9_\\-]{0,63}'} required/></label>
      <button className="primary" disabled={!toolName || (transport === 'mcp' ? !remoteName : !executable)}>保存自定义工具并绑定</button>
    </fieldset>
  </form>;
}

type ToolResourceAction = { owner: string; reference: string; requestId: string; action: 'bind' | 'sharing'; visibility?: 'personal' | 'team' };
function ToolResourceActions({ ownerId, record, disabled, onChanged }: { ownerId: string; record: PersonalToolConnection; disabled: boolean; onChanged: () => void }) {
  const storage = `factory-tool-action:${encodeURIComponent(ownerId)}:${record.registrationRef}`;
  const [pending, setPending] = useState<ToolResourceAction | null>(() => {
    try {
      const value = JSON.parse(localStorage.getItem(storage) ?? 'null') as ToolResourceAction;
      return value?.owner === ownerId && value.reference === record.registrationRef && identifier(value.requestId)
        && (value.action === 'bind' || value.action === 'sharing' && ['personal', 'team'].includes(value.visibility ?? '')) ? value : null;
    } catch { return null; }
  });
  const [busy, setBusy] = useState(false); const [message, setMessage] = useState(''); const lock = useRef(false);
  async function act(action: 'bind' | 'sharing') {
    if (lock.current || disabled) return;
    lock.current = true; setBusy(true); setMessage('');
    const original = pending;
    try {
      if ((await api.session()).id !== ownerId) throw new ToolConnectionError(403, 'EXPECTED_OWNER_MISMATCH');
      const command: ToolResourceAction = original ?? { owner: ownerId, reference: record.registrationRef,
        requestId: crypto.randomUUID(), action, ...(action === 'sharing' ? { visibility: record.visibility === 'team' ? 'personal' : 'team' } : {}) };
      localStorage.setItem(storage, JSON.stringify(command)); setPending(command);
      if (command.action === 'bind') {
        const value = original ? (await personalToolConnectionApi.recoverBinding(ownerId, command.requestId)).connection
          : await personalToolConnectionApi.bind(ownerId, record.registrationRef, command.requestId, record.capabilities);
        if (value.registrationRef !== record.registrationRef) throw new Error('Unexpected binding');
      } else if (original) {
        const receipt = await personalToolConnectionApi.recover(ownerId, command.requestId);
        if (receipt.action !== 'tool.sharing' || receipt.tool.registrationRef !== record.registrationRef) throw new Error('Unexpected sharing');
      } else {
        await personalToolConnectionApi.sharing(ownerId, record.registrationRef, command.visibility!, command.requestId);
      }
      localStorage.removeItem(storage); setPending(null); onChanged();
      setMessage(command.action === 'bind' ? '工具连接已核对。' : '共享设置已核对。');
    } catch (error) {
      if (!original && error instanceof ToolConnectionError && [400, 401, 403, 404, 422].includes(error.status)) {
        localStorage.removeItem(storage); setPending(null); setMessage('操作未被接受。');
      } else setMessage('原请求尚待核对。');
    } finally { lock.current = false; setBusy(false); }
  }
  return <div>{message && <p role="status">{message}</p>}{pending
    ? <button disabled={disabled || busy} onClick={() => { void act(pending.action); }}>核对原工具操作</button>
    : <>{record.allowedActions.includes('bind') && <button disabled={disabled || busy} onClick={() => { void act('bind'); }}>绑定此工具</button>}{record.allowedActions.includes('sharing') && <button disabled={disabled || busy} onClick={() => { void act('sharing'); }}>{record.visibility === 'team' ? '设为个人工具' : '共享给团队'}</button>}</>}</div>;
}
