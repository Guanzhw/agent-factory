import { useEffect, useRef, useState } from 'react';
import { api } from './api.js';
import type { PersonalCredential } from './personalRemoteApi.js';
import { personalToolConnectionApi as tools, publicToolConfiguration, ToolConnectionError, type CreateToolAccount, type CreateToolOperation, type ToolOperation } from './personalToolConnectionApi.js';

type Request = { owner: string; kind: 'operation'; input: CreateToolOperation }
  | { owner: string; kind: 'account'; operationId: string; input: CreateToolAccount };
const id = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_.:@-]{1,200}$/.test(value);
export function readToolOperationRequest(raw: string | null, owner: string): Request | null {
  try {
    const value = JSON.parse(raw ?? 'null');
    if (!value || value.owner !== owner || !value.input || !id(value.input.requestId)) return null;
    const input = value.input;
    if (value.kind === 'operation' && Object.keys(value).every(key => ['owner', 'kind', 'input'].includes(key))
        && Object.keys(input).every(key => ['configuration', 'requestId', 'operationId'].includes(key))
        && (input.operationId === undefined || id(input.operationId))) {
      return { owner, kind: 'operation', input: { requestId: input.requestId,
        configuration: publicToolConfiguration(input.configuration), ...(input.operationId ? { operationId: input.operationId } : {}) } };
    }
    if (value.kind === 'account' && id(value.operationId) && Object.keys(value).every(key => ['owner', 'kind', 'input', 'operationId'].includes(key))
        && Object.keys(input).every(key => ['version', 'sha256', 'requestId', 'credentialRef', 'credentialRevision'].includes(key))
        && Number.isSafeInteger(input.version) && input.version > 0 && /^[a-f0-9]{64}$/.test(input.sha256)
        && (input.credentialRef === undefined && input.credentialRevision === undefined || id(input.credentialRef) && id(input.credentialRevision))) {
      return { owner, kind: 'account', operationId: value.operationId, input: { ...input } };
    }
  } catch { /* Corrupt or private configuration never becomes a public retry. */ }
  return null;
}
const blankRecipe = JSON.stringify({ transport: 'cli', toolName: '', description: '', inputSchema: { type: 'object', properties: {} }, executable: '', arguments: [], environment: {}, argumentOptions: {}, stdinJson: true, outputFormat: 'json', readOnly: false, timeoutSeconds: 30, maxOutputBytes: 65536 }, null, 2);
const pin = (value: ToolOperation) => `${value.operationRef.id}:${value.operationRef.version}:${value.operationRef.sha256}`;

export function ReusableToolOperations({ ownerId, credentials, disabled, onChanged }: {
  ownerId: string; credentials: PersonalCredential[]; disabled: boolean; onChanged: () => void;
}) {
  const storage = `factory-public-tool-request:${encodeURIComponent(ownerId)}`;
  const [pending, setPending] = useState<Request | null>(() => { try { return readToolOperationRequest(localStorage.getItem(storage), ownerId); } catch { return null; } });
  const [open, setOpen] = useState(!!pending);
  const [operations, setOperations] = useState<ToolOperation[]>([]);
  const [selected, setSelected] = useState(''); const [selectedCredential, setSelectedCredential] = useState('');
  const [recipe, setRecipe] = useState(blankRecipe); const [operationId, setOperationId] = useState('');
  const [confirmed, setConfirmed] = useState(false); const [busy, setBusy] = useState(false);
  const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [refresh, setRefresh] = useState(0);
  const [ready, setReady] = useState(false); const [ownerChanged, setOwnerChanged] = useState(false);
  const lock = useRef(false); const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  async function verifyOwner() {
    if ((await api.session()).id !== ownerId) {
      if (alive.current) { setOwnerChanged(true); setOperations([]); setRecipe(blankRecipe); setConfirmed(false); setSelectedCredential(''); }
      throw new ToolConnectionError(403, 'EXPECTED_OWNER_MISMATCH');
    }
    if (!alive.current) throw new Error('Unmounted');
  }
  useEffect(() => {
    if (!open || ownerChanged) return;
    const controller = new AbortController(); setReady(false);
    void (async () => {
      await verifyOwner();
      const values = await tools.operations(ownerId, controller.signal);
      if (!controller.signal.aborted && alive.current) { setOperations(values); setReady(true); setError(''); }
    })().catch(() => { if (!controller.signal.aborted && alive.current) setError('暂时无法读取公开操作。请重新读取；其他工具连接仍可使用。'); });
    return () => controller.abort();
  }, [ownerId, open, refresh, ownerChanged]);
  const chosen = operations.find(value => pin(value) === selected);
  const matching = credentials.filter(value => value.status === 'active' && value.providerId === chosen?.descriptor.credentialProviderId && value.destination === chosen?.descriptor.credentialDestination);
  const credential = matching.find(value => value.credentialRef === selectedCredential);
  let configuration: CreateToolOperation['configuration'] | undefined;
  try { configuration = publicToolConfiguration(JSON.parse(recipe)); } catch { /* Preview requires a valid public recipe. */ }
  function retain(value: Request | null) {
    if (value) localStorage.setItem(storage, JSON.stringify(value)); else localStorage.removeItem(storage);
    if (alive.current) setPending(value);
  }
  async function submit(request: Request, retry = false) {
    if (lock.current || disabled || ownerChanged || !retry && pending) return;
    lock.current = true; setBusy(true); setError(''); setNotice('');
    try {
      await verifyOwner();
      // Keep only explicitly submitted public recipe or account reference metadata.
      // An uncertain acknowledgement locks the exact request, including its credentials.
      if (!retry) retain(request);
      if (request.kind === 'operation') {
        const result = await tools.createOperation(ownerId, request.input);
        if (!alive.current) return;
        setSelected(pin(result)); setConfirmed(false);
        setNotice('公开操作版本已保存。尚未创建账号、发布工具材料或执行工具；材料可使用下方固定运行声明。');
      } else {
        await tools.createOperationAccount(ownerId, request.operationId, request.input);
        if (!alive.current) return;
        setNotice('已为此公开操作创建本人的独立账号。请在工具列表中绑定连接；其他成员的账号与凭据保持独立。');
      }
      retain(null); setRefresh(value => value + 1); onChanged();
    } catch (failure) {
      if (!alive.current) return;
      const rejected = failure instanceof ToolConnectionError && [400, 401, 403, 404, 405, 413, 415, 422].includes(failure.status);
      if (rejected) retain(null);
      setError(failure instanceof ToolConnectionError && failure.code === 'EXPECTED_OWNER_MISMATCH'
        ? '当前登录账号已改变，请刷新后管理本人的操作与凭据。'
        : rejected ? '公开操作或账号请求未被接受，请检查输入。' : '请求尚未确认。请核对原请求；将使用完全相同的内容与请求标识，不会改用其他凭据。');
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  const blocked = disabled || busy || !!pending || ownerChanged;
  return <section aria-label="可复用工具操作"><button className="secondary" disabled={busy} aria-expanded={open} onClick={() => setOpen(value => !value)}>可复用工具操作</button>{open && <>
    <p>公开操作固定目标与调用配方；每位成员可连接自己的独立账号，也可继续使用已有团队连接。</p>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {pending && <aside className="state-note"><p>原{pending.kind === 'operation' ? '公开操作' : '独立账号'}请求待确认。输入已锁定，刷新后仍核对同一请求。</p><pre aria-label="待确认原请求">{JSON.stringify(pending, null, 2)}</pre><button disabled={disabled || busy || ownerChanged} onClick={() => void submit(pending, true)}>核对原操作请求</button></aside>}
    <button className="secondary" disabled={busy || ownerChanged} onClick={() => setRefresh(value => value + 1)}>重新读取公开操作</button>
    <form aria-label="创建可复用操作" className="material-editor" onSubmit={event => { event.preventDefault(); if (configuration && confirmed) void submit({ owner: ownerId, kind: 'operation', input: { configuration, requestId: crypto.randomUUID(), ...(operationId ? { operationId } : {}) } }); }}>
      <h3>创建可复用操作</h3><p>配方、CLI 参数与环境变量、工作目录及 MCP 目标将对成员公开。这里只填写可公开内容；秘密应通过账号凭据注入，不得写入 URL 或配方。此操作不会复制已有私有工具配置。</p>
      <fieldset disabled={blocked}><label>操作版本<select aria-label="公开操作版本目标" value={operationId} onChange={event => { setOperationId(event.target.value); setConfirmed(false); }}><option value="">创建新操作</option>{[...new Map(operations.filter(value => value.ownerId === ownerId).map(value => [value.operationRef.id, value])).values()].map(value => <option key={value.operationRef.id} value={value.operationRef.id}>{value.descriptor.toolName} · 保存新版本</option>)}</select></label>
        <label>公开配方（JSON）<textarea aria-label="公开操作配方" rows={12} value={recipe} onChange={event => { setRecipe(event.target.value); setConfirmed(false); }}/></label>
        <p className="quiet">MCP 使用 transport: "mcp"、url 与 remoteToolName；CLI 使用 executable、arguments、workingDirectory、environment、argumentOptions、stdinJson、credentialEnvironmentVariable 与 outputFormat。两者均可填写 inputSchema、readOnly、timeoutSeconds 和 maxOutputBytes。</p>
        {!configuration && <p role="status">请填写有效配方。仅接受公开配置字段，不接受凭据引用或包含认证信息的 URL。</p>}
        {configuration && <div aria-label="即将公开的完整配方"><h4>即将公开的完整配方</h4><pre>{JSON.stringify(configuration, null, 2)}</pre></div>}
        <label><input aria-label="确认公开操作配方" type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)}/>我确认以上全部配方可向成员公开，秘密通过账号凭据单独提供。</label>
        <button className="primary" disabled={!configuration || !confirmed}>保存公开操作版本</button>
      </fieldset>
    </form>
    <form aria-label="为公开操作连接账号" onSubmit={event => { event.preventDefault(); if (chosen && (!selectedCredential || credential)) void submit({ owner: ownerId, kind: 'account', operationId: chosen.operationRef.id, input: { version: chosen.operationRef.version, sha256: chosen.operationRef.sha256, requestId: crypto.randomUUID(), ...(credential ? { credentialRef: credential.credentialRef, credentialRevision: credential.credentialRevision } : {}) } }); }}>
      <h3>为此操作连接账号</h3><fieldset disabled={blocked || !ready}><label>公开操作<select aria-label="选择公开工具操作" value={selected} onChange={event => { setSelected(event.target.value); setSelectedCredential(''); }}><option value="">选择固定版本</option>{selected && !chosen && <option value={selected} disabled>原操作版本当前不可用</option>}{operations.map(value => <option key={pin(value)} value={pin(value)}>{value.descriptor.toolName} · v{value.operationRef.version} · {value.ownerId}</option>)}</select></label>
        {chosen && <><p>操作作者：{chosen.ownerId}；新账号及凭据所有者：{ownerId}。保存账号不会执行工具或验证服务。</p><pre aria-label="所选操作公开配方">{JSON.stringify(chosen.configuration, null, 2)}</pre><label>本人账号凭据<select aria-label="公开操作本人凭据" value={selectedCredential} onChange={event => setSelectedCredential(event.target.value)}><option value="">无需凭据</option>{matching.map(value => <option key={value.credentialRef} value={value.credentialRef}>{value.credentialRef} · {value.credentialRevision}</option>)}</select></label><p className="quiet">仅列出本人的有效凭据：{chosen.descriptor.credentialProviderId} · {chosen.descriptor.credentialDestination}。新凭据请先在凭据入口单独保存。</p><details><summary>工具材料固定运行声明</summary><pre>{JSON.stringify(chosen.runtimeBinding, null, 2)}</pre><span>操作 SHA-256 {chosen.operationRef.sha256}；这不是材料摘要。</span></details></>}
        <button className="primary" disabled={!chosen || !!selectedCredential && !credential}>创建本人的独立账号</button>
      </fieldset>
    </form>
  </>}</section>;
}
