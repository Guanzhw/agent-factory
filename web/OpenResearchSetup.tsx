import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api.js';
import { PersonalRemotes } from './PersonalRemotes.js';
import { personalRemoteApi } from './personalRemoteApi.js';
import { personalOrxProjectApi } from './personalOrxProjectApi.js';
import { ORX_PERSONAL_PROVIDER } from './personalAgentApi.js';
import type { User, UserConnection } from './models.js';

export function OpenResearchSetup({ ownerId, onConnected }: { ownerId: string; onConnected: (ref: string) => void }) {
  const [user, setUser] = useState<User>(); const [refs, setRefs] = useState<UserConnection[]>([]);
  const [source, setSource] = useState(''); const [projects, setProjects] = useState<{ nativeProjectId: string; name: string; path: string }[]>([]);
  const [serviceNames, setServiceNames] = useState<Record<string, string>>({});
  const [project, setProject] = useState(''); const [busy, setBusy] = useState(false); const [notice, setNotice] = useState('');
  const [revision, refresh] = useState(0); const lock = useRef(false); const live = useRef(true);
  const storage = `factory-orx-project-selection:${encodeURIComponent(ownerId)}`;
  const [pending, setPending] = useState(() => { try { return localStorage.getItem(storage) ?? ''; } catch { return ''; } });
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  useEffect(() => {
    const ctrl = new AbortController();
    void Promise.all([api.session(ctrl.signal), api.userConnections(ctrl.signal), personalRemoteApi.list(ctrl.signal)]).then(([who, connections, remotes]) => {
      if (ctrl.signal.aborted) return;
      if (who.id !== ownerId || connections.some(c => c.ownerId !== ownerId)) throw new Error('owner');
      setUser(who); setServiceNames(Object.fromEntries(remotes.map(r => [r.registrationRef, r.origin])));
      const eligible = connections.filter(c => c.available && c.status === 'active' && c.taskId === null && c.capabilities.includes('project:create') && remotes.some(r => r.registrationRef === c.registrationRef && r.providerId === ORX_PERSONAL_PROVIDER));
      setRefs(eligible); setSource(old => eligible.some(c => c.ref === old) ? old : eligible[0]?.ref ?? '');
    }).catch(() => { if (!ctrl.signal.aborted) { setUser(undefined); setNotice('暂时无法核对连接。恢复连接后刷新，研究草稿会保留。'); } });
    return () => ctrl.abort();
  }, [ownerId, revision]);
  useEffect(() => {
    const ctrl = new AbortController(); setProjects([]); setProject('');
    if (source) void personalOrxProjectApi.existing(source, ctrl.signal).then(rows => {
      if (!ctrl.signal.aborted) { setProjects(rows); setProject(rows[0]?.nativeProjectId ?? ''); }
    }).catch(() => { if (!ctrl.signal.aborted) setNotice('无法读取上游项目，请重新验证连接。'); });
    return () => ctrl.abort();
  }, [source, revision]);
  async function connect(recover = false) {
    if (lock.current || !user || !recover && (!source || !project || pending)) return;
    lock.current = true; setBusy(true); setNotice('');
    try {
      const who = await api.session(); if (!live.current || who.id !== ownerId) { setUser(undefined); return; }
      let id = pending;
      if (!recover) { id = crypto.randomUUID(); localStorage.setItem(storage, id); setPending(id); }
      const connection = recover ? await personalOrxProjectApi.recoverSelected(id, ownerId) : await personalOrxProjectApi.selectExisting(source, project, id, ownerId);
      if (!live.current) return;
      if (connection.ownerId !== ownerId || connection.kind !== 'orx' || !connection.capabilities.includes('session:read')) throw new Error('scope');
      localStorage.removeItem(storage); setPending(''); onConnected(connection.ref);
    } catch (error) {
      if (live.current) {
        // A partial local setup may exist: even a failed POST is recovered read-only.
        setNotice(error instanceof ApiError && error.status === 404 && recover ? '还未找到最终绑定回执。保留原请求继续核对；不会重新配置或启动研究。' : '连接结果尚未确认。请核对原请求，研究草稿已保留。');
      }
    } finally { lock.current = false; if (live.current) setBusy(false); }
  }
  return <section className="research-setup" aria-label="补齐研究连接"><h3>连接 OpenResearch</h3>
    {notice && <p role="status">{notice}</p>}
    {pending && <p role="alert">上次连接待核对。<button disabled={busy} onClick={() => void connect(true)}>核对原连接</button><details><summary>请求详情</summary>{pending}</details></p>}
    {!!refs.length && <><label>服务连接<select aria-label="研究服务连接" value={source} disabled={busy || !!pending} onChange={e => setSource(e.target.value)}>{refs.map(r => <option key={r.ref} value={r.ref}>{serviceNames[r.registrationRef] || '已验证的 OpenResearch 服务'}</option>)}</select></label>
      {projects.length ? <><label>研究项目<select aria-label="研究项目" value={project} disabled={busy || !!pending} onChange={e => setProject(e.target.value)}>{projects.map(p => <option key={p.nativeProjectId} value={p.nativeProjectId}>{p.name || '未命名项目'}</option>)}</select></label><p>使用此项目，并沿用已有会话的远端模型、工具权限与计划配置。这里只读验证并保存个人绑定；点击“开始研究”才创建会话并发送目标。</p><button className="primary" disabled={busy || !!pending || !project} onClick={() => void connect()}>使用此项目</button></> : <p>此服务还没有可读取的项目。新项目需要明确远端路径与模型配置，请展开下方“新建远端项目”完成创建；研究草稿保留。</p>}</>}
    <details open={!refs.length}><summary>{refs.length ? '添加或修复服务连接' : '首次服务配置'}</summary>{user && <PersonalRemotes user={user} jobs={[]} researchSetup onChanged={() => refresh(n => n + 1)} />}</details>
  </section>;
}
