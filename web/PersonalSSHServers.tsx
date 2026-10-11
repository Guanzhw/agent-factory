import { useEffect, useRef, useState } from 'react';
import { api } from './api.js';
import { credentialReceipt, matchCredentialReceipt, SSH_CREDENTIAL_PROVIDER } from './credentialManagement.js';
import { personalRemoteApi, RemoteRequestError, type PersonalCredential } from './personalRemoteApi.js';
import { personalSSHApi, sshMessages, type PersonalSSHServer, type SSHAction, type SSHIdentity, type SSHIdentityInput } from './personalSSHApi.js';

type Pending = { owner: string; requestId: string; action: SSHAction | 'credential'; reference?: string; input?: SSHIdentityInput;
  destination?: string; credentialRef?: string; credentialRevision?: string };
const empty: SSHIdentityInput = { name: '', address: '', port: 22, username: '', hostKey: '', allowedRoot: '' };
const identifier = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_.:@-]{1,200}$/.test(value);
function readPending(value: unknown, owner: string): Pending | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const p = value as Pending;
  if (p.owner !== owner || !identifier(p.requestId) || !['credential', 'configure', 'verify', 'bind', 'revoke'].includes(p.action) ||
      Object.keys(p).some(k => !['owner', 'requestId', 'action', 'reference', 'input', 'destination', 'credentialRef', 'credentialRevision'].includes(k)) ||
      p.reference !== undefined && !/^remote-[a-f0-9]{32}$/.test(p.reference) ||
      ['verify', 'bind', 'revoke'].includes(p.action) && !p.reference) return null;
  if (p.action === 'credential' || p.action === 'configure') {
    const i = p.input;
    if (!i || Object.keys(i).sort().join(',') !== 'address,allowedRoot,hostKey,name,port,username' ||
        [i.name, i.address, i.username, i.hostKey, i.allowedRoot].some(v => typeof v !== 'string' || v.length > 200 || /[\r\n]/.test(v)) ||
        !Number.isInteger(i.port) || i.port < 1 || i.port > 65535) return null;
    if (p.action === 'credential' && (typeof p.destination !== 'string' || !p.destination.startsWith('ssh://'))) return null;
    if (p.action === 'configure' && (!identifier(p.credentialRef) || !identifier(p.credentialRevision))) return null;
  }
  return p;
}
function serverReceipt(value: PersonalSSHServer): PersonalSSHServer {
  if (!value || !/^remote-[a-f0-9]{32}$/.test(value.reference) || typeof value.enabled !== 'boolean' ||
      typeof value.name !== 'string' || typeof value.hostKey !== 'string' || typeof value.hostFingerprint !== 'string' ||
      typeof value.allowedRoot !== 'string' || !identifier(value.credentialRef) || !identifier(value.credentialRevision)) throw new Error('Invalid server receipt');
  return value;
}

type Props = { ownerId: string; onChanged: () => void; onResearch?: () => void; revision?: number };
export function PersonalSSHServers(props: Props) {
  return <OwnerSSHServers key={props.ownerId} {...props}/>;
}
function OwnerSSHServers({ ownerId, onChanged, onResearch, revision = 0 }: Props) {
  const storage = `factory-personal-ssh:${encodeURIComponent(ownerId)}`;
  const [pending, setPending] = useState<Pending | null>(() => { try { return readPending(JSON.parse(localStorage.getItem(storage) ?? 'null'), ownerId); } catch { return null; } });
  const [archived, setArchived] = useState<Pending[]>(() => { try { const a: unknown = JSON.parse(localStorage.getItem(`${storage}:unresolved`) ?? '[]'); return Array.isArray(a) ? a.slice(0, 100).map(v => readPending(v, ownerId)).filter((p): p is Pending => !!p) : []; } catch { return []; } });
  const [ready, setReady] = useState(false); const [enabled, setEnabled] = useState(false); const [blocked, setBlocked] = useState(false);
  const [rows, setRows] = useState<PersonalSSHServer[]>([]); const [credentials, setCredentials] = useState<PersonalCredential[]>([]);
  const [input, setInput] = useState<SSHIdentityInput>(pending?.input ?? empty); const [form, setForm] = useState(!!pending?.input);
  const [editing, setEditing] = useState<string>(); const [identity, setIdentity] = useState<SSHIdentity>();
  const [credential, setCredential] = useState<PersonalCredential>(); const [privateKey, setPrivateKey] = useState(''); const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [refresh, setRefresh] = useState(0);
  const [confirmStop, setConfirmStop] = useState(false); const [revoking, setRevoking] = useState<string>();
  const alive = useRef(true); const lock = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  function clearSecret() { setPrivateKey(''); setConsent(false); }
  function accountChanged() { clearSecret(); setRows([]); setCredentials([]); setInput(empty); setIdentity(undefined); setCredential(undefined); setForm(false); setPending(null); setArchived([]); setReady(false); setBlocked(true); setError('登录账户已改变，SSH 输入已清空。请刷新后管理自己的服务器。'); }
  async function verifyOwner() { const s = await api.session(); if (!alive.current) throw new Error('Unmounted'); if (s.id !== ownerId) { accountChanged(); throw new RemoteRequestError(true, 'EXPECTED_OWNER_MISMATCH'); } }
  useEffect(() => {
    const ctrl = new AbortController(); setReady(false);
    void (async () => {
      await verifyOwner(); const cap = await personalSSHApi.capabilities(ownerId, ctrl.signal);
      if (typeof cap.enabled !== 'boolean') throw new Error('Invalid capability');
      const [servers, saved] = cap.enabled ? await Promise.all([personalSSHApi.list(ownerId, ctrl.signal), personalRemoteApi.credentials(ctrl.signal, ownerId)]) : [[], []];
      await verifyOwner();
      if (!ctrl.signal.aborted && alive.current) { setRows(servers.map(serverReceipt)); setCredentials(saved.map(credentialReceipt).filter(c => c.providerId === SSH_CREDENTIAL_PROVIDER && c.status === 'active')); setEnabled(cap.enabled); setReady(true); }
    })().catch(e => { if (!ctrl.signal.aborted && alive.current) { if (e instanceof RemoteRequestError && e.code === 'EXPECTED_OWNER_MISMATCH') accountChanged(); else setError('暂时无法读取自己的服务器，请重新读取。原记录保留。'); } });
    return () => ctrl.abort();
  }, [ownerId, refresh, revision]);
  useEffect(() => {
    if (ready && credential && !credentials.some(c => c.credentialRef === credential.credentialRef && c.credentialRevision === credential.credentialRevision && c.status === 'active')) {
      setCredential(undefined); clearSecret();
      setNotice('SSH 身份版本已改变或撤销，请重新选择当前身份并确认授权。');
    }
  }, [ready, credentials, credential]);
  function retain(p: Pending) { localStorage.setItem(storage, JSON.stringify(p)); setPending(p); }
  function acknowledge(p: Pending, archive = false) {
    if (archive) { const next = archived.filter(v => v.requestId !== p.requestId); localStorage.setItem(`${storage}:unresolved`, JSON.stringify(next)); setArchived(next); }
    else { localStorage.removeItem(storage); setPending(null); }
    setConfirmStop(false);
  }
  function changed() { setRefresh(n => n + 1); onChanged(); }
  async function run(work: () => Promise<void>) {
    if (lock.current || blocked) return; lock.current = true; setBusy(true); setError(''); setNotice('');
    try { await verifyOwner(); await work(); }
    catch (e) { if (alive.current) { clearSecret(); if (e instanceof RemoteRequestError && e.code === 'EXPECTED_OWNER_MISMATCH') accountChanged(); else setError(e instanceof RemoteRequestError && e.code && sshMessages[e.code] ? sshMessages[e.code] : '操作尚未确认。请先核对原操作，页面不会自动重发。'); } }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  async function preview() {
    if (!ready || pending) return;
    await run(async () => { const result = await personalSSHApi.identity(ownerId, input); await verifyOwner(); if (alive.current) { setIdentity(result); clearSecret(); setCredential(undefined); } });
  }
  async function configure(saved: PersonalCredential, profile: SSHIdentityInput, reference?: string) {
    await verifyOwner();
    const p: Pending = { owner: ownerId, action: 'configure', requestId: crypto.randomUUID(), input: profile, credentialRef: saved.credentialRef, credentialRevision: saved.credentialRevision, ...(reference ? { reference } : {}) };
    retain(p);
    try {
      serverReceipt(await personalSSHApi.configure(ownerId, { ...profile, credentialRef: saved.credentialRef, credentialRevision: saved.credentialRevision, confirmedHostKey: true, requestId: p.requestId }, reference));
      await verifyOwner(); if (alive.current) { acknowledge(p); setForm(false); setIdentity(undefined); setCredential(undefined); setNotice('服务器已登记。下一步检查连接与依赖；此时尚未安装应用。'); changed(); }
    } catch (e) { if (e instanceof RemoteRequestError && e.rejected && alive.current) acknowledge(p); throw e; }
  }
  async function save() {
    if (!ready || pending || !identity || !consent || (!credential && !privateKey)) return;
    const profile = { ...input, address: identity.address, username: identity.username, hostKey: identity.hostKey };
    await run(async () => {
      let saved = credential;
      if (!saved) {
        const p: Pending = { owner: ownerId, action: 'credential', requestId: crypto.randomUUID(), input: profile, destination: identity.origin, ...(editing ? { reference: editing } : {}) };
        retain(p); const secret = privateKey; clearSecret();
        try {
          saved = matchCredentialReceipt(await personalRemoteApi.saveCredential({ providerId: SSH_CREDENTIAL_PROVIDER, destination: identity.origin, username: identity.username, password: secret, requestId: p.requestId }, ownerId),
            { owner: ownerId, action: 'create', requestId: p.requestId, providerId: SSH_CREDENTIAL_PROVIDER, destination: identity.origin });
          await verifyOwner(); if (!alive.current) return; acknowledge(p); setCredential(saved);
        } catch (e) { if (e instanceof RemoteRequestError && e.rejected && alive.current) acknowledge(p); throw e; }
      }
      if (saved) await configure(saved, profile, editing);
    });
  }
  async function command(server: PersonalSSHServer, action: Exclude<SSHAction, 'configure'>) {
    if (!ready || pending) return;
    await run(async () => {
      const p: Pending = { owner: ownerId, action, reference: server.reference, requestId: crypto.randomUUID() }; retain(p);
      try {
        serverReceipt(await personalSSHApi.command(ownerId, server.reference, action, p.requestId)); await verifyOwner();
        if (alive.current) { acknowledge(p); setRevoking(undefined); setNotice(action === 'verify' ? '连接与依赖已通过。确认启用后，可去 OpenResearch 准备研究应用。' : action === 'bind' ? '服务器已启用，可去 OpenResearch 准备研究。' : '连接授权已撤销，已有研究数据保留。'); changed(); }
      } catch (e) {
        if (e instanceof RemoteRequestError && e.rejected && alive.current) {
          if (action === 'verify' && e.code && sshMessages[e.code]) {
            const diagnostic = e.code;
            setRows(previous => previous.map(row => row.reference === server.reference ? { ...row, status: 'failed', enabled: false, diagnostic, lastCheckRequestId: p.requestId } : row));
          }
          acknowledge(p); changed();
        }
        throw e;
      }
    });
  }
  async function recover(p: Pending, archive = false) {
    await run(async () => {
      if (p.action === 'credential') {
        const saved = matchCredentialReceipt(await personalRemoteApi.recoverCredential(p.requestId, ownerId), { owner: ownerId, action: 'create', requestId: p.requestId, providerId: SSH_CREDENTIAL_PROVIDER, destination: p.destination! });
        await verifyOwner(); if (alive.current) {
          const pin = new URL(saved.destination).searchParams.get('hostkey')!;
          const bytes = pin.match(/../g)!.map(v => parseInt(v, 16));
          acknowledge(p, archive); clearSecret(); setInput(p.input!); setEditing(p.reference);
          setIdentity({ address: p.input!.address, port: p.input!.port, username: p.input!.username, hostKey: p.input!.hostKey,
            hostFingerprint: 'SHA256:' + btoa(String.fromCharCode(...bytes)).replace(/=+$/, ''), origin: saved.destination });
          setCredential(saved); setForm(true); setNotice('身份保存已确认。请重新确认授权后登记服务器；核对没有重发私钥。'); changed();
        }
      } else {
        let receipt;
        try { receipt = await personalSSHApi.recover(ownerId, p.requestId, p.action); }
        catch (e) {
          if (p.action === 'verify' && p.reference) {
            const current = serverReceipt(await personalSSHApi.inspect(ownerId, p.reference));
            if (current.lastCheckRequestId === p.requestId && current.diagnostic) { await verifyOwner(); if (alive.current) { acknowledge(p, archive); setError(sshMessages[current.diagnostic] ?? '依赖检查未通过，请核对服务器后重新检查。'); changed(); } return; }
          }
          throw e;
        }
        if (receipt.requestId !== p.requestId || receipt.action !== p.action || p.reference && receipt.server.reference !== p.reference) throw new Error('Receipt mismatch');
        serverReceipt(receipt.server); await verifyOwner();
        if (alive.current) { acknowledge(p, archive); setNotice('原操作已确认，已读取当前服务器状态。没有重放检查、启用或安装。'); if (p.action === 'configure') setForm(false); changed(); }
      }
    });
  }
  function stopWaiting() {
    if (!pending || archived.length >= 100) return;
    void run(async () => { const next = [...archived, pending]; localStorage.setItem(`${storage}:unresolved`, JSON.stringify(next)); setArchived(next); acknowledge(pending); clearSecret(); setForm(false); setIdentity(undefined); setCredential(undefined); setNotice('已停止等待，原操作仍可核对。它可能已经完成；请先查看最新服务器和已保存身份，再决定新操作。'); changed(); });
  }
  function begin(server?: PersonalSSHServer) { clearSecret(); setCredential(undefined); setIdentity(undefined); setEditing(server?.reference); setInput(server ? { name: server.name, address: server.address, port: server.port, username: server.username, hostKey: server.hostKey, allowedRoot: server.allowedRoot } : empty); setForm(true); setError(''); }
  function go(server: PersonalSSHServer) { sessionStorage.setItem(`factory-research-server:${encodeURIComponent(ownerId)}`, JSON.stringify({ owner: ownerId, reference: server.reference, directory: server.defaultDirectory })); onResearch?.(); }
  const disabled = busy || blocked || !!pending || !ready;
  return <section className="personal-ssh" aria-labelledby="personal-ssh-title"><h2 id="personal-ssh-title">我的 Linux 服务器</h2><p>登记自己的服务器与 SSH 身份，检查依赖，选择私有目录，再到 OpenResearch 准备研究应用。个人使用无需逐台管理员登记。</p>
    <p className="quiet">需已有 Linux x86-64、Python 3.12+、Docker 和非 root SSH/Docker 权限。这里只安装研究应用，不自动安装系统依赖。</p>
    {error && <p className="error-message" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    <button disabled={busy || blocked} onClick={() => setRefresh(n => n + 1)}>重新读取服务器</button>
    {!ready && !error && <p role="status">正在读取自己的服务器…</p>}{ready && !enabled && <p className="state-note">此部署尚未启用个人 SSH 服务器功能。部署方启用通用运行包与凭据保险库后，你可自行登记服务器。</p>}
    {pending && <div className="state-note"><h3>上次操作待确认</h3><p>私钥输入已清空。核对只读取原结果，不会重发或安装。</p><button disabled={busy || blocked} onClick={() => void recover(pending)}>核对原操作</button><button disabled={busy || blocked || archived.length >= 100} onClick={() => setConfirmStop(true)}>停止等待</button>{confirmStop && <div><p>停止等待不会取消原操作，它仍可能完成。将保留原结果核对入口，任何新操作都需重新确认。</p><button disabled={busy} onClick={stopWaiting}>确认停止等待并保留记录</button><button disabled={busy} onClick={() => setConfirmStop(false)}>继续等待</button></div>}</div>}
    {!!archived.length && <details><summary>未确认的保留操作</summary>{archived.map(p => <p key={p.requestId}>原操作仍可核对。<button disabled={disabled || form} onClick={() => void recover(p, true)}>核对保留结果</button></p>)}</details>}
    {rows.map(server => <article className="model-record" key={server.reference}><h3>{server.name}</h3><p>{server.username}@{server.address}:{server.port} · {server.allowedRoot}</p><p role="status">{server.enabled ? '已启用，可准备研究' : server.status === 'verified' ? '依赖已通过，请确认启用' : server.status === 'revoked' ? '连接授权已撤销' : server.status === 'expired' ? '检查授权已到期，请重新检查并启用' : server.status === 'credential_unavailable' ? 'SSH 身份不可用，请更换连接设置' : '需要检查连接与依赖'}</p><p className="quiet">检查授权有效 15 分钟。到期后重新检查并启用，原研究数据保留。</p>{server.diagnostic && <p className="error-message">{sshMessages[server.diagnostic] ?? '依赖检查未通过。'}</p>}
      {server.status !== 'revoked' && <div className="button-row"><button disabled={disabled} onClick={() => void command(server, 'verify')}>检查连接与依赖</button>{server.status === 'verified' && !server.enabled && <button disabled={disabled} onClick={() => void command(server, 'bind')}>启用此服务器</button>}{server.enabled && onResearch && <button className="primary" disabled={disabled} onClick={() => go(server)}>去 OpenResearch 准备</button>}<button disabled={disabled} onClick={() => begin(server)}>更换连接设置</button><button disabled={disabled} onClick={() => setRevoking(server.reference)}>撤销授权</button></div>}
      {revoking === server.reference && <div><p>确认撤销 {server.name} 的后续连接授权？原研究数据保留。</p><button disabled={disabled} onClick={() => void command(server, 'revoke')}>确认撤销服务器授权</button><button disabled={busy} onClick={() => setRevoking(undefined)}>保留授权</button></div>}</article>)}
    {ready && enabled && !form && !pending && <><p>{!rows.length && '还没有自己的服务器。先添加并检查，再开始研究。'}</p><button disabled={disabled} onClick={() => begin()}>添加我的服务器</button></>}
    {form && !pending && !blocked && <form className="model-form" aria-label="设置我的服务器" onSubmit={e => { e.preventDefault(); void (identity ? save() : preview()); }}><h3>{identity ? '确认服务器身份与授权' : editing ? '更换服务器连接设置' : '添加我的服务器'}</h3>
      <fieldset disabled={disabled || !!identity}><label>服务器名称<input value={input.name} maxLength={80} onChange={e => setInput({ ...input, name: e.target.value })}/></label><label>服务器 IP<input value={input.address} autoComplete="off" onChange={e => setInput({ ...input, address: e.target.value })}/></label><label>SSH 端口<input type="number" min={1} max={65535} value={input.port} onChange={e => setInput({ ...input, port: Number(e.target.value) })}/></label><label>SSH 账户<input value={input.username} autoComplete="off" onChange={e => setInput({ ...input, username: e.target.value })}/></label><label>服务器 Ed25519 主机公钥<textarea rows={2} value={input.hostKey} autoComplete="off" maxLength={200} placeholder="ssh-ed25519 AAAA…" onChange={e => setInput({ ...input, hostKey: e.target.value })}/></label><details><summary>如何取得主机公钥？</summary><p>从服务器本机终端或可信管理控制台读取 <code>cat /etc/ssh/ssh_host_ed25519_key.pub</code>，复制完整公钥。这里不会从未确认的网络连接自动学习主机身份。</p></details><label>私有工作目录<input value={input.allowedRoot} autoComplete="off" placeholder="/home/me/.agent-factory" maxLength={80} onChange={e => setInput({ ...input, allowedRoot: e.target.value })}/></label><p>检查时不创建目录；准备研究应用时可在本人已有目录下创建这个私有子目录，不修改其他目录权限。</p></fieldset>
      {identity && <fieldset disabled={disabled}><p>主机指纹：<code>{identity.hostFingerprint}</code></p><label>已保存的此服务器 SSH 身份<select value={credential?.credentialRef ?? ''} onChange={e => { setCredential(credentials.find(c => c.credentialRef === e.target.value)); setPrivateKey(''); }}><option value="">输入一个专用身份</option>{credentials.filter(c => c.destination === identity.origin).map((c, i) => <option key={c.credentialRef} value={c.credentialRef}>已保存身份 {i + 1}</option>)}</select></label>{!credential && <><label>专用 SSH 私钥（Ed25519）<textarea rows={4} autoComplete="off" maxLength={4096} value={privateKey} onChange={e => setPrivateKey(e.target.value)}/></label><p className="quiet">使用服务器已授权的、无口令专用 Ed25519 私钥。它仅加密保存在保险库，不回显或写入浏览器存储；带口令密钥暂不支持。</p></>}
        <label><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/>我已从可信来源核对主机公钥，授权 Factory 使用此 SSH 身份连接自己的服务器、检查依赖，并在选定私有目录准备研究应用。</label></fieldset>}
      <div className="button-row"><button className="primary" disabled={disabled || !input.name || !input.address || !input.username || !input.hostKey || !input.allowedRoot || !!identity && (!consent || !credential && !privateKey)}>{identity ? '保存身份并登记服务器' : '核对服务器身份'}</button>{identity && <button type="button" disabled={busy} onClick={() => { clearSecret(); setIdentity(undefined); setCredential(undefined); }}>修改服务器信息</button>}<button type="button" disabled={busy} onClick={() => { clearSecret(); setForm(false); setIdentity(undefined); setCredential(undefined); }}>取消并清空输入</button></div>
    </form>}
  </section>;
}
