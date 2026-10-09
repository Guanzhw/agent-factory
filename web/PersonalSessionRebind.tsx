import { useEffect, useRef, useState } from 'react';
import { api } from './api.js';
import type { UserConnection } from './models.js';
import type { PersonalNamespace, PersonalSession } from './personalAgentApi.js';
import { checkedRebindRecovery, checkRebindPreview, checkRebindReceipt, personalRebindApi, rebindRecovery, type RebindPreview, type RebindRecovery } from './personalRebindApi.js';

type Props = { ownerId: string; namespace: PersonalNamespace; session?: PersonalSession; candidates: UserConnection[]; commandPending: boolean; disabled: boolean; onRebound: (session: PersonalSession) => void; onPending: (pending: boolean) => void };
export function PersonalSessionRebind(props: Props) { return <RebindPanel key={`${props.ownerId}:${props.namespace}`} {...props} />; }
function RebindPanel({ ownerId, namespace, session, candidates, commandPending, disabled, onRebound, onPending }: Props) {
  const storage = `factory-personal-rebind:${encodeURIComponent(ownerId)}:${namespace}`;
  const [pending, setPending] = useState<RebindRecovery | null>(() => { try { return checkedRebindRecovery(JSON.parse(localStorage.getItem(storage) ?? 'null')); } catch { return null; } });
  const pendingRef = useRef(pending); pendingRef.current = pending;
  const [target, setTarget] = useState(''); const [preview, setPreview] = useState<RebindPreview>(); const [busy, setBusy] = useState(false); const [notice, setNotice] = useState('');
  const lock = useRef(false); const alive = useRef(true); const scope = `${session?.id ?? ''}:${session?.connectionPin?.fingerprint ?? ''}:${target}`; const currentScope = useRef(scope); currentScope.current = scope;
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => { onPending(!!pending); return () => onPending(false); }, [pending, onPending]);
  useEffect(() => { setPreview(undefined); }, [scope]);
  const oldPin = session?.connectionPin;
  const eligible = candidates.filter(candidate => candidate.ownerId === ownerId && candidate.available && candidate.status === 'active' && candidate.ref !== oldPin?.ref && candidate.kind === oldPin?.kind && candidate.taskId === null && oldPin?.taskId === null && candidate.capabilities.every(cap => oldPin.capabilities.includes(cap)));
  async function work(operation: () => Promise<void>) { if (lock.current) return; lock.current = true; setBusy(true); onPending(true); try { await operation(); } catch { if (alive.current) setNotice('续接尚未确认或范围不匹配。保留原会话与原请求；不会创建替代会话或重发远程命令。'); } finally { lock.current = false; if (alive.current) { setBusy(false); onPending(!!pendingRef.current); } } }
  async function inspect() {
    const candidate = eligible.find(item => item.ref === target); if (disabled || pending || !session?.nativeSessionId || !oldPin || !candidate) return; const started = scope;
    await work(async () => {
      const who = await api.session(); if (!alive.current || currentScope.current !== started || who.id !== ownerId) return;
      const result = checkRebindPreview(await personalRebindApi.preview(session.id, candidate.ref, oldPin.fingerprint), session, candidate, ownerId);
      if (!alive.current || currentScope.current !== started) return;
      setPreview(result); setNotice(result.canRebind ? '已只读核对同一原生会话与新旧绑定。尚未续接；需要下方单独确认。' : '原轮次仍未解决，不能续接。请核对原请求；未知确认不能通过换绑定绕过。');
    });
  }
  async function commit() {
    const candidate = eligible.find(item => item.ref === target); if (disabled || commandPending || pending || !preview?.canRebind || !session || !candidate) return; const started = scope;
    await work(async () => {
      const who = await api.session(); if (!alive.current || currentScope.current !== started || who.id !== ownerId) return;
      checkRebindPreview(preview, session, candidate, ownerId);
      const intent = rebindRecovery(preview, session, crypto.randomUUID());
      localStorage.setItem(storage, JSON.stringify(intent)); pendingRef.current = intent; setPending(intent);
      const result = checkRebindReceipt(await personalRebindApi.commit(intent), intent, ownerId, namespace);
      if (!alive.current || currentScope.current !== started) return;
      localStorage.removeItem(storage); pendingRef.current = null; setPending(null); setPreview(undefined); setTarget(''); setNotice('已续接同一原生会话，仅更新后续连接。原结果、原命令与原方案引用保持不变；没有启动远程工作。'); onRebound(result.session);
    });
  }
  async function recover() {
    if (!pending) return;
    await work(async () => {
      const who = await api.session(); if (!alive.current || who.id !== ownerId) return;
      const result = checkRebindReceipt(await personalRebindApi.recover(pending.requestId), pending, ownerId, namespace);
      if (!alive.current) return;
      localStorage.removeItem(storage); pendingRef.current = null; setPending(null); setPreview(undefined); setTarget(''); setNotice('已读取原续接回执；没有重复续接或创建会话。原任务引用保持不变。'); onRebound(result.session);
    });
  }
  if (!pending && !session) return null;
  return <section aria-label="续接原生会话"><h3>续接同一原生会话</h3><p>连接到期或凭据轮换后，先在资源设置重新验证并单独绑定，再选择新的本人连接。续接只更新本地后续连接，不创建会话、不发送消息、不授予新权限。</p>
    {session && <p>原绑定：{session.connectionRef} · {session.bindingStatus ?? '状态待核对'}。原生项目 {session.nativeProjectId} · 原生会话 {session.nativeSessionId ?? '确认未知'}</p>}
    {notice && <p role="status">{notice}</p>}
    {pending ? <p role="alert">原续接请求：{pending.requestId}<button disabled={busy} onClick={() => void recover()}>核对原续接请求</button></p> : <>
      {!oldPin && <p>缺少原绑定指纹，不能续接。请刷新原会话记录。</p>}
      <label>新的已验证本人绑定<select aria-label="新的已验证本人绑定" value={target} disabled={busy || disabled || !oldPin} onChange={event => { setTarget(event.target.value); setPreview(undefined); }}><option value="">选择新绑定，预览核对同提供方和目标</option>{eligible.map(item => <option key={item.ref} value={item.ref}>{item.ref}</option>)}</select></label>
      {!eligible.length && <p>尚无不扩大原能力范围的新绑定。请先完成资源验证与明确绑定。</p>}
      <button disabled={busy || disabled || !target || !oldPin || !session?.nativeSessionId} onClick={() => void inspect()}>只读预览原会话续接</button>
      {preview && <div><p>原指纹：{preview.oldConnectionPin.fingerprint}</p><p>新指纹：{preview.newConnectionPin.fingerprint}</p><p>原生项目 {preview.nativeProjectId} · 原生会话 {preview.nativeSessionId} · 能力范围不扩大</p>{preview.blocker && <p role="alert">续接受阻：{preview.blocker}。请继续核对原请求，不要重建会话。</p>}{preview.blockers?.map(item => <p key={`${item.requestId}:${item.source}`}>原请求 {item.requestId} · {item.action === 'interrupt' ? '中断请求' : '消息请求'} · {item.state} · 来源：{item.source === 'durable-command-ledger' ? '持久命令记录' : '原活动请求'}。远程停止未经证实。</p>)}{commandPending && <p>先核对当前原命令回执，再确认续接。</p>}<button disabled={busy || disabled || commandPending || !preview.canRebind} onClick={() => void commit()}>确认续接同一原生会话</button><button disabled={busy} onClick={() => setPreview(undefined)}>取消续接预览</button></div>}
    </>}
    {!!session?.bindingHistory?.length && <details><summary>历史绑定与原任务引用</summary>{session.bindingHistory.map(entry => <p key={entry.requestId}>{entry.oldConnectionPin.ref} → {entry.newConnectionPin.ref} · 原续接请求 {entry.requestId}</p>)}<p>原方案 {session.factoryIdentity?.planId ?? '只读关联，没有初始命令方案'} · 原任务 {session.factoryIdentity?.taskId ?? '无'}</p></details>}
  </section>;
}
