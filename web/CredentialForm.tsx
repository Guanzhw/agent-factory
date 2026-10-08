import { useRef, useState } from 'react';
import { personalRemoteApi, RemoteRequestError, type PersonalCredential } from './personalRemoteApi.js';

export function CredentialForm({ owner, providerId, destination, onSaved, onCancel, credentialKind = 'password' }: { credentialKind?: 'password' | 'service-token'; owner: string; providerId: string; destination: string; onSaved: (value: PersonalCredential) => void; onCancel: () => void }) {
  // Persist only an opaque command ID, never credentials or a hash of credentials.
  const storageKey = `factory-credential-pending:${encodeURIComponent(owner)}`;
  const [requestId, setRequestId] = useState(() => { try { return window.localStorage.getItem(storageKey) ?? ''; } catch { return ''; } });
  const [username, setUsername] = useState(''); const serviceToken = credentialKind === 'service-token'; const [password, setPassword] = useState('');
  const [consent, setConsent] = useState(false); const [busy, setBusy] = useState(false); const [unknown, setUnknown] = useState(!!requestId);
  const pending = useRef(false); const [rejected, setRejected] = useState(false);
  function accepted(value: PersonalCredential, recovered = false) {
    if ((!recovered && (value.providerId !== providerId || value.destination !== destination)) || typeof value.providerId !== 'string' || typeof value.destination !== 'string' || value.status !== 'active' || !value.credentialRef || !value.credentialRevision) throw new Error('Invalid credential receipt');
    try { window.localStorage.removeItem(storageKey); } catch { /* No secrets are persisted. */ }
    setUsername(''); setPassword(''); setRequestId(''); setUnknown(false); onSaved(value);
  }
  async function save() {
    if (pending.current || unknown || !consent || !serviceToken && !username || !password) return;
    pending.current = true; setBusy(true); setRejected(false); const id = crypto.randomUUID(); setRequestId(id);
    try { window.localStorage.setItem(storageKey, id); } catch { setRequestId(''); setRejected(true); setUsername(''); setPassword(''); setConsent(false); setBusy(false); pending.current = false; return; }
    try { accepted(await personalRemoteApi.saveCredential({ providerId, destination, username: serviceToken ? 'bearer' : username, password, requestId: id })); }
    catch (error) {
      setUsername(''); setPassword('');
      if (error instanceof RemoteRequestError && error.rejected) {
        setRejected(true); setUnknown(false); setRequestId(''); setConsent(false);
        try { window.localStorage.removeItem(storageKey); } catch { /* No secrets persisted. */ }
      } else setUnknown(true);
    }
    finally { setBusy(false); pending.current = false; }
  }
  async function recover() {
    if (pending.current || !requestId) return;
    pending.current = true; setBusy(true);
    try { accepted(await personalRemoteApi.recoverCredential(requestId), true); }
    catch { setUnknown(true); }
    finally { setBusy(false); pending.current = false; }
  }
  return <form className="material-editor" aria-label="安全保存个人凭据" onSubmit={event => { event.preventDefault(); void save(); }}>
    <h3>保存到服务器凭据保险库</h3><p>提供方 {providerId} · 仅用于 {destination}。凭据由当前登录用户持有；不会作为材料或提示词保存。</p>
    <p>这里只保存远程服务登录凭据，模型密钥留在远程服务。{serviceToken && '请填写已有 OpenResearch 服务令牌，不要填写模型 API 密钥。'}</p>
    <fieldset disabled={busy || unknown}>{!serviceToken && <label>服务用户名<input aria-label="服务用户名" value={username} autoComplete="off" onChange={event => setUsername(event.target.value)} /></label>}
      <label>{serviceToken ? 'OpenResearch 服务令牌' : '服务密码'}<input aria-label={serviceToken ? 'OpenResearch 服务令牌' : '服务密码'} type="password" value={password} autoComplete="new-password" onChange={event => setPassword(event.target.value)} /></label>
      <label><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} />我同意将此凭据保存到已部署的服务器保险库，并用于此目标的后续显式验证与已批准会话请求。</label>
    </fieldset>
    {rejected && <p role="alert">请求未保存：服务已拒绝，或浏览器无法持久保存恢复标识。请检查输入、权限和浏览器存储后重新填写。</p>}
    {unknown && <div role="alert"><p>凭据保存结果未知，已清空输入且禁止重复提交。只读取原请求回执；若仍未确认，请由部署管理员核对。关闭表单不代表保存已撤销。</p><p>原请求标识：{requestId}</p><button type="button" disabled={busy} onClick={() => void recover()}>核对原凭据请求</button></div>}
    <button className="primary" disabled={busy || unknown || !consent || !serviceToken && !username || !password}>{busy ? '等待保存确认…' : '确认安全保存凭据'}</button>
    <button type="button" className="secondary" disabled={busy} onClick={() => { setUsername(''); setPassword(''); onCancel(); }}>取消并清空</button>
  </form>;
}
