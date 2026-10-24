import { useEffect, useState } from 'react';
import { accountApi, type Account, type AccountChange } from './accountApi.js';
import { ErrorMessage } from './workspaceUI.js';

function AccountEditor({ account, disabled, save }: { account: Account; disabled: boolean; save: (id: string, change: AccountChange) => Promise<void> }) {
  const [name, setName] = useState(account.name);
  const [email, setEmail] = useState(account.email ?? '');
  return <article className="material-row review-row"><form className="material-editor" aria-label={`账号 ${account.id}`} onSubmit={event => { event.preventDefault(); void save(account.id, { name, ...(email ? { email } : {}) }); }}>
    <h2>{account.id}</h2><p>{account.disabled ? '已停用' : '已启用'} · {account.accountAdmin ? '账号管理员' : '成员'}</p>
    <fieldset disabled={disabled}><label>姓名<input aria-label={`${account.id} 姓名`} required value={name} onChange={event => setName(event.target.value)}/></label><label>邮箱<input aria-label={`${account.id} 邮箱`} type="email" value={email} onChange={event => setEmail(event.target.value)}/></label>
    <div className="material-actions"><button className="secondary" type="submit">保存账号信息</button><button type="button" className="secondary" onClick={() => void save(account.id, { disabled: !account.disabled })}>{account.disabled ? '启用账号' : '停用账号'}</button><button type="button" className="secondary" onClick={() => void save(account.id, { accountAdmin: !account.accountAdmin })}>{account.accountAdmin ? '设为成员' : '设为账号管理员'}</button></div></fieldset>
  </form></article>;
}

export function AccountManagement() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [id, setId] = useState('');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [accountAdmin, setAccountAdmin] = useState(false);
  useEffect(() => {
    const controller = new AbortController(); setReady(false); setError('');
    void accountApi.list(offset, controller.signal).then(page => {
      if (!controller.signal.aborted) { setAccounts(page.accounts); setTotal(page.total); setReady(true); }
    }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '账号读取失败。'); });
    return () => controller.abort();
  }, [offset, refresh]);
  async function mutate(work: () => Promise<unknown>) {
    setBusy(true); setError(''); setNotice('');
    try { await work(); setNotice('账号已更新。'); setRefresh(value => value + 1); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '账号更新失败。'); }
    finally { setBusy(false); }
  }
  return <section aria-labelledby="accounts-title"><div className="page-heading"><div><h1 id="accounts-title">账号管理</h1><p>管理成员账号、启停状态与账号管理员身份。所有成员均可使用工作流、组件并管理自己的资源。</p></div><button disabled={busy} className="secondary" onClick={() => setRefresh(value => value + 1)}>刷新账号</button></div>
    <ErrorMessage message={error}/>{notice && <p role="status">{notice}</p>}
    <form className="material-editor" onSubmit={event => { event.preventDefault(); void mutate(async () => { await accountApi.create({ id, name: name || undefined, email: email || undefined, accountAdmin }); setId(''); setName(''); setEmail(''); setAccountAdmin(false); }); }}><h2>新增成员账号</h2><fieldset disabled={busy}><div className="editor-grid"><label>账号标识<input aria-label="账号标识" required value={id} onChange={event => setId(event.target.value)}/></label><label>姓名<input aria-label="新账号姓名" value={name} onChange={event => setName(event.target.value)}/></label><label>邮箱<input aria-label="新账号邮箱" type="email" value={email} onChange={event => setEmail(event.target.value)}/></label></div><label><input type="checkbox" checked={accountAdmin} onChange={event => setAccountAdmin(event.target.checked)}/>账号管理员</label><button className="primary" type="submit">新增账号</button></fieldset></form>
    {ready ? accounts.map(account => <AccountEditor key={`${account.id}:${refresh}`} account={account} disabled={busy} save={(accountId, change) => mutate(() => accountApi.update(accountId, change))}/>) : !error && <p role="status">正在读取账号…</p>}
    {ready && <div className="material-actions"><span>共 {total} 个账号</span>{offset > 0 && <button disabled={busy} onClick={() => setOffset(Math.max(0, offset - 100))}>上一页</button>}{offset + accounts.length < total && <button disabled={busy} onClick={() => setOffset(offset + 100)}>下一页</button>}</div>}
  </section>;
}
