import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api.js';
import { PersonalRemotes } from './PersonalRemotes.js';
import { personalRemoteApi } from './personalRemoteApi.js';
import { personalOrxProjectApi, type ProjectSelectionStatus } from './personalOrxProjectApi.js';
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
  const [retained, setRetained] = useState<string[]>(() => { try { const rows: unknown = JSON.parse(localStorage.getItem(storage + ':retained') ?? '[]'); return Array.isArray(rows) ? rows.filter((r): r is string => typeof r === 'string') : []; } catch { return []; } });
  const [status, setStatus] = useState<ProjectSelectionStatus>();
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
  function retain(id: string) {
    const rows = [...new Set([...retained, id])];
    // Preserve the pointer before unlocking. Storage failure leaves it pending.
    localStorage.setItem(storage + ':retained', JSON.stringify(rows)); setRetained(rows);
    localStorage.removeItem(storage); setPending('');
  }
  function adopt(connection: UserConnection) {
    if (connection.ownerId !== ownerId || connection.kind !== 'orx' || !connection.capabilities.includes('session:read')) throw new Error('scope');
    localStorage.removeItem(storage); setPending(''); setStatus(undefined); onConnected(connection.ref);
  }
  function showStatus(value: ProjectSelectionStatus, id: string) {
    setStatus(value);
    if (value.state === 'complete' && value.connection) { adopt(value.connection); return; }
    if (value.state === 'failed') {
      retain(id);
      const reason = value.failureStatus === 403 ? '请核对当前配置权限。' : value.failureStatus === 404 ? '所选项目或连接已不可读取，请重新选择。' : '请修复服务连接或项目验证。';
      setNotice((value.localConfiguration === 'partial' ? '本次连接配置已失败，部分本地配置已保存。原记录保留；可以修复服务或更换项目后明确重新选择。没有启动研究。' : '本次连接配置已被拒绝，未保存本地配置。原记录保留；可以更换项目或连接后明确重新选择。没有启动研究。') + reason);
    } else setNotice(value.localConfiguration === 'partial' ? '已有部分本地配置，最终结果仍未知。保留原记录核对，或明确离开本次配置；不会自动重发。' : '连接结果仍未知。未找到配置回执不代表从未执行；请核对或保留记录后更换连接。');
  }
  async function leavePending() {
    if (lock.current || !pending) return;
    lock.current = true; setBusy(true);
    try {
      const who = await api.session(); if (!live.current || who.id !== ownerId) { setUser(undefined); return; }
      retain(pending); setStatus(undefined); setNotice('原连接结果仍未知，核对记录已保留。可明确选择其他项目或连接；原请求不会自动重发，也没有发送研究目标。');
    } catch { if (live.current) setNotice('无法保留或核对原记录，尚未解锁。请恢复连接或浏览器存储后重试。'); }
    finally { lock.current = false; if (live.current) setBusy(false); }
  }
  async function connect(recover = false, retainedId?: string) {
    if (lock.current || !user || !recover && (!source || !project || pending)) return;
    lock.current = true; setBusy(true); setNotice('');
    try {
      const who = await api.session(); if (!live.current || who.id !== ownerId) { setUser(undefined); return; }
      let id = retainedId ?? pending;
      if (!recover) { id = crypto.randomUUID(); localStorage.setItem(storage, id); setPending(id); setStatus(undefined); }
      if (recover) {
        const value = await personalOrxProjectApi.recoverSelected(id, ownerId);
        if (live.current) showStatus(value, id);
      } else {
        try { const connection = await personalOrxProjectApi.selectExisting(source, project, id, ownerId); if (live.current) adopt(connection); }
        catch (error) {
          // Read a terminal/partial receipt after an error; never replay POST.
          try { const value = await personalOrxProjectApi.recoverSelected(id, ownerId); if (live.current) showStatus(value, id); }
          catch { throw error; }
        }
      }
    } catch (error) {
      if (live.current) {
        setNotice(error instanceof ApiError && error.status === 404 && recover ? '还未找到配置回执。单次未找到不能证明从未执行；请保留原记录核对或明确更换连接。' : '连接结果尚未确认。请核对原请求，研究草稿已保留。');
      }
    } finally { lock.current = false; if (live.current) setBusy(false); }
  }
  return <section className="research-setup" aria-label="补齐研究连接"><h3>连接 OpenResearch</h3>
    {notice && <p role="status">{notice}</p>}
    {pending && <div role="alert"><p>上次连接待核对。{status?.localConfiguration === 'partial' && '已有部分本地配置。'}</p><button disabled={busy || !user} onClick={() => void connect(true)}>核对原连接</button><p>离开只解除本页配置选择限制，保留原请求供核对，不取消原配置、不重发操作或凭据。</p><button disabled={busy || !user} onClick={() => void leavePending()}>保留原记录，改用其他项目或连接</button><details><summary>请求详情</summary>{pending}</details></div>}
    {!!retained.length && <details><summary>保留的连接配置记录</summary>{retained.map(id => <p key={id}>{id}<button disabled={busy || !!pending || !user} onClick={() => void connect(true, id)}>核对并使用已确认连接</button></p>)}</details>}
    {!!refs.length && <><label>服务连接<select aria-label="研究服务连接" value={source} disabled={busy || !!pending} onChange={e => setSource(e.target.value)}>{refs.map(r => <option key={r.ref} value={r.ref}>{serviceNames[r.registrationRef] || '已验证的 OpenResearch 服务'}</option>)}</select></label>
      {projects.length ? <><label>研究项目<select aria-label="研究项目" value={project} disabled={busy || !!pending} onChange={e => setProject(e.target.value)}>{projects.map(p => <option key={p.nativeProjectId} value={p.nativeProjectId}>{p.name || '未命名项目'}</option>)}</select></label><p>使用此项目，并沿用已有会话的远端模型、工具权限与计划配置。这里只读验证并保存个人绑定；点击“开始研究”才创建会话并发送目标。</p><button className="primary" disabled={busy || !!pending || !project} onClick={() => void connect()}>使用此项目</button></> : <p>此服务还没有可读取的项目。新项目需要明确远端路径与模型配置，请展开下方“新建远端项目”完成创建；研究草稿保留。</p>}</>}
    <details open={!refs.length}><summary>{refs.length ? '添加或修复服务连接' : '首次服务配置'}</summary>{user && <PersonalRemotes user={user} jobs={[]} researchSetup onChanged={() => refresh(n => n + 1)} />}</details>
  </section>;
}
