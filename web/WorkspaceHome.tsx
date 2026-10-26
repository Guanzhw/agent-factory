import { useEffect, useState, type ReactNode } from 'react';
import { IconArrowRight, IconBox, IconFileText, IconServer } from '@tabler/icons-react';
import { ApplicationCatalog, type InstalledApplication } from './ApplicationCatalog.js';
import type { WorkspaceContext } from './App.js';
import { ownerModelApi } from './ownerModelApi.js';
import { personalSSHApi, serverReceipt, sshMessages } from './personalSSHApi.js';
import { Badge, time } from './workspaceUI.js';

type Summary = { text: string; note?: string };
type ReadState = { value?: Summary; loading: boolean; error?: string };
type Props = { applications: readonly InstalledApplication[]; context: WorkspaceContext };

export function WorkspaceHome(props: Props) {
  return <OwnerHome key={props.context.user.id} {...props}/>;
}

function OwnerHome({ applications, context }: Props) {
  const { user, jobs, jobsLoaded, jobsError, onTask, navigate, retry, refreshRevision, openApplication } = context;
  const [model, setModel] = useState<ReadState>({ loading: true });
  const [servers, setServers] = useState<ReadState>({ loading: true });
  useEffect(() => {
    const controller = new AbortController();
    async function read(set: typeof setModel, request: () => Promise<Summary>) {
      set(current => ({ ...current, loading: true, error: undefined }));
      try {
        const value = await request();
        if (!controller.signal.aborted) set({ value, loading: false });
      } catch {
        if (!controller.signal.aborted) set(current => ({ ...current, loading: false, error: '暂时无法读取' }));
      }
    }
    void read(setModel, async () => {
      const capabilities = await ownerModelApi.capabilities(controller.signal);
      if (!capabilities.enabled) return { text: '此部署未启用模型设置' };
      const records = await ownerModelApi.list(user.id, controller.signal);
      const selected = records.find(record => record.isDefault && record.available);
      if (selected) return { text: `默认：${selected.model}`, note: selected.isOwner ? undefined : '使用团队共享模型' };
      return { text: records.some(record => record.isDefault) ? '默认模型需处理'
        : records.some(record => record.available) ? '尚未选择默认模型' : records.length ? '暂无可用模型' : '未设置',
      note: capabilities.credentialsEnabled === false ? '密钥保存未启用；仍可配置无需认证的服务。' : undefined };
    });
    void read(setServers, async () => {
      const capabilities = await personalSSHApi.capabilities(user.id, controller.signal);
      if (typeof capabilities.enabled !== 'boolean') throw new Error('Invalid SSH capability');
      if (!capabilities.enabled) return { text: '此部署未启用服务器接入' };
      const records = (await personalSSHApi.list(user.id, controller.signal)).map(serverReceipt);
      if (capabilities.controllerDiagnostic) return { text: '控制端需要处理', note: sshMessages[capabilities.controllerDiagnostic] ?? '请在服务器设置中查看当前控制端状态。' };
      return { text: !records.length ? '按需添加' : records.some(record => record.enabled) ? '已有启用的连接'
        : records.every(record => record.status === 'revoked') ? '暂无可用主机' : '已登记，需检查或启用' };
    });
    return () => controller.abort();
  }, [user.id, refreshRevision]);
  const ownJobs = jobs.filter(job => job.ownerId === user.id);
  const taskError = ownJobs.length !== jobs.length ? '任务归属待核对，请重新读取。' : jobsError;
  return <div className="workspace-home">
    <ApplicationCatalog applications={applications} onSelect={openApplication}/>
    <section className="home-section" aria-labelledby="home-tasks-title">
      <div className="section-heading"><h2 id="home-tasks-title">我的任务</h2><button className="text-button home-link" onClick={() => navigate({ tab: 'tasks' })}>查看全部<IconArrowRight size={18} aria-hidden="true"/></button></div>
      {taskError && <p className="home-read-error" role="alert">{ownJobs.length && ownJobs.length === jobs.length ? '任务更新失败，保留上次记录。' : '暂时无法读取任务。'}<button className="text-button" onClick={retry}>重新读取任务</button></p>}
      {!jobsLoaded && !taskError ? <p className="home-empty" role="status">正在读取任务…</p>
        : ownJobs.length && ownJobs.length === jobs.length ? <ul className="home-task-list">{ownJobs.slice(0, 3).map(job => <li key={job.id}><button onClick={() => onTask(job.id)}><span><strong>{job.input.topic}</strong><small>{time(job.createdAt)}</small></span><Badge value={job.status}/><IconArrowRight size={18} aria-hidden="true"/></button></li>)}</ul>
          : !taskError && <div className="home-empty"><IconFileText size={38} aria-hidden="true"/><h3>暂无任务</h3><p>在应用中提交目标后，这里会显示进度与结果。</p></div>}
    </section>
    <section className="home-section" aria-labelledby="home-resources-title">
      <h2 id="home-resources-title">我的资源</h2>
      <div className="home-resource-list">
        <ResourceRow label="模型与密钥" icon={<IconBox size={23}/>} state={model} retry={retry} action="去设置" onClick={() => navigate({ tab: 'models', modelReturn: 'catalog' })}/>
        <ResourceRow label="远程主机" icon={<IconServer size={23}/>} state={servers} retry={retry} action="管理资源" onClick={() => navigate({ tab: 'connections', resource: 'servers' })}/>
      </div>
    </section>
  </div>;
}

function ResourceRow({ label, icon, state, action, onClick, retry }: {
  label: string; icon: ReactNode; state: ReadState; action: string; onClick: () => void; retry: () => void;
}) {
  return <div className="home-resource-row">
    <span className="home-resource-name"><span aria-hidden="true">{icon}</span><strong>{label}</strong></span>
    <div className="home-resource-status">
      {state.value && <><span>{state.value.text}</span>{state.value.note && <small>{state.value.note}</small>}</>}
      {state.loading && <small role="status">{state.value ? '正在更新…' : '正在读取…'}</small>}
      {state.error && <small role="alert">{state.value ? '更新失败，保留上次记录。' : `${state.error}。`}<button className="text-button" onClick={retry}>重新读取{label}</button></small>}
    </div>
    <button className="text-button home-link" onClick={onClick}>{action}<IconArrowRight size={18} aria-hidden="true"/></button>
  </div>;
}
