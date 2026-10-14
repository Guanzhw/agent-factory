/** Static deployment assembly. Applications do not install code through declarations. */
import { useState } from 'react';
import App, { Workspace as WorkspaceShell, type WorkspaceSessionProps, type WorkspaceContext } from './App.js';
import { api } from './api.js';
import { ApplicationComposer, type ComposerSeed } from './ApplicationComposer.js';
import { ResourceCenter } from './ResourceCenter.js';
import { ModelSettings } from './ModelSettings.js';
import { ConnectionsPanel } from './ConnectionsPanel.js';
import { SchedulesPanel } from './SchedulesPanel.js';
import { ScheduleDiagnostics } from './ScheduleDiagnostics.js';
import { StoragePanel } from './StoragePanel.js';
import { MaterialGovernancePanel } from './MaterialGovernance.js';
import { ApplicationGovernance } from './ApplicationGovernance.js';
import { TaskWorkspace } from './TaskWorkspace.js';
import { researchNavigation } from '../apps/research/web/navigation.js';
import { ResearchCatalog, ResearchDeveloperTools, ResearchPages } from '../apps/research/web/ResearchPages.js';
import { ResearchTaskDetail } from '../apps/research/web/ResearchTaskDetail.js';
import { ResearchPlanReviews } from '../apps/research/web/ResearchPlanReviews.js';
import { PersonalRemotes } from '../apps/research/web/PersonalRemotes.js';
import { composerModeLabels, taskModeLabels } from '../apps/research/web/modeLabels.js';
import { jobDisplayTitle } from '../apps/research/web/nativeCommandDisplay.js';

export default function ComposedApp() { return <App workspace={Workspace}/>; }
export function Workspace(props: WorkspaceSessionProps) {
  return <WorkspaceShell {...props} navigation={researchNavigation}>{context => <Pages context={context}/>}</WorkspaceShell>;
}
function Pages({ context: original }: { context: WorkspaceContext }) {
  const [seed, setSeed] = useState<ComposerSeed>();
  const [schedule, setSchedule] = useState<{ planId: string; planFingerprint: string; goal: string }>();
  const context: WorkspaceContext = { ...original, onCompose: (next, notice) => { setSeed(next); original.navigate({ tab: 'developer' }); original.notice(notice); } };
  const { route, user, navigate, materials, targets, jobs, busy, act, notice, onTask } = context;
  const tab = route.tab;
  return <>
    {tab === 'catalog' && <section><div className="page-heading"><div><p className="quiet">FACTORY / 应用目录</p><h1>选择你的工作区</h1><p>进入应用提出目标，在任务中查看执行与证据。开始前可在资源中接入自己的模型与服务器。</p></div></div><div className="or-catalog-grid"><ResearchCatalog context={context}/><article className="or-catalog-card"><span className="quiet">开始前的准备</span><h2>接入我的资源</h2><p>设置默认模型，选择平台环境或接入自己的服务器。已有项目与会话可以继续使用原连接。</p><button className="secondary" onClick={() => navigate({ tab: 'resources' })}>查看我的资源</button></article></div></section>}
    {tab === 'resources' && <ResourceCenter onModels={() => navigate({ tab: 'models', modelReturn: 'resources' })} onConnections={() => navigate({ tab: 'connections' })} applicationLabel="OpenResearch" onResearch={() => navigate({ tab: 'openresearch' })}/>}
    {tab === 'models' && <ModelSettings key={`ModelSettings:${user.id}`} ownerId={user.id} onResearch={() => navigate({ tab: route.modelReturn ?? 'catalog' })} onCredentials={() => navigate({ tab: 'connections' })}/>}
    <ResearchPages context={context}/>
    {tab === 'developer' && <section><div className="page-heading"><div><h1>开发者装配</h1><p>高级材料与应用契约验证。Checksum 仅为开发示例。</p></div></div><ApplicationComposer key={seed?.key ?? 'ordinary'} seed={seed} modeLabels={composerModeLabels} onSchedule={plan => { setSchedule({ planId: plan.id, planFingerprint: plan.fingerprint, goal: plan.normalizedGoal }); navigate({ tab: 'schedules' }); }} user={user} busy={busy} act={act} materials={materials} targets={targets} onCreated={id => { onTask(id); notice('创建请求已确认。请在任务记录中查看进度与结果。'); }}/><ResearchDeveloperTools context={context}/></section>}
    {tab === 'research' && <TaskWorkspace context={context} Detail={ResearchTaskDetail} title={jobDisplayTitle} modeLabels={taskModeLabels} emptyContent={<><p>选择已有任务查看进度、待回答问题与证据。要发起或继续研究，请进入 OpenResearch。</p><button className="secondary" onClick={() => navigate({ tab: 'openresearch' })}>进入 OpenResearch</button></>}/>}
    {tab === 'schedules' && <><ScheduleDiagnostics key={`diagnostics:${user.id}`} ownerId={user.id} api={api.scheduleDiagnostics}/><SchedulesPanel key={`SchedulesPanel:${user.id}`} ownerId={user.id} canManage={!!user} seed={schedule} api={api.schedules} disabled={!!busy} onTask={onTask}/></>}
    {tab === 'storage' && <StoragePanel key={`StoragePanel:${user.id}`} ownerId={user.id} busy={busy} act={act} onNotice={notice}/>}
    {tab === 'connections' && <ConnectionsPanel user={user} jobs={jobs} busy={busy} act={act} onNotice={notice} onModels={() => navigate({ tab: 'models', modelReturn: 'connections' })} applicationLabel="OpenResearch" onResearch={() => navigate({ tab: 'openresearch' })} onPrepareResearch={() => navigate({ tab: 'openresearch', mode: 'personal', project: '' })} remoteServices={(refresh, onChanged) => <PersonalRemotes key={`${user.id}:${refresh}`} user={user} jobs={jobs} onTask={onTask} onChanged={onChanged}/>}/>}
    {tab === 'materials' && <MaterialGovernancePanel user={user} materials={materials} busy={busy} act={act} onNotice={notice}/>}
    {tab === 'applications' && <ApplicationGovernance user={user} materials={materials} busy={busy} act={act} onNotice={notice}/>}
    {tab === 'reviews' && <ResearchPlanReviews ownerId={user.id} busy={busy} act={act}/>}
  </>;
}
