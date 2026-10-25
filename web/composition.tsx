/** Static deployment assembly. Applications do not install code through declarations. */
import { useState } from 'react';
import App, { Workspace as WorkspaceShell, type WorkspaceSessionProps, type WorkspaceContext } from './App.js';
import { api } from './api.js';
import { ApplicationComposer, type ComposerSeed } from './ApplicationComposer.js';
import { ApplicationCatalog, type InstalledApplication } from './ApplicationCatalog.js';
import { AccountManagement } from './AccountManagement.js';
import { ResourceCenter } from './ResourceCenter.js';
import { ModelSettings } from './ModelSettings.js';
import { ConnectionsPanel } from './ConnectionsPanel.js';
import { SchedulesPanel } from './SchedulesPanel.js';
import { ScheduleDiagnostics } from './ScheduleDiagnostics.js';
import { StoragePanel } from './StoragePanel.js';
import { MaterialGovernancePanel } from './MaterialGovernance.js';
import { ApplicationGovernance } from './ApplicationGovernance.js';
import { PlanReviews } from './PlanReviews.js';
import { PersonalRemotes } from './PersonalRemotes.js';
import { TaskWorkspace } from './TaskWorkspace.js';

// Register installed application entries here; catalog rendering stays in the platform.
const installedApplications: readonly InstalledApplication[] = [];

export default function ComposedApp() { return <App workspace={Workspace}/>; }
export function Workspace(props: WorkspaceSessionProps) {
  return <WorkspaceShell {...props}>{context => <Pages context={context}/>}</WorkspaceShell>;
}
function Pages({ context: original }: { context: WorkspaceContext }) {
  const [seed, setSeed] = useState<ComposerSeed>();
  const [schedule, setSchedule] = useState<{ planId: string; planFingerprint: string; goal: string }>();
  const context: WorkspaceContext = { ...original, onCompose: (next, notice) => { setSeed(next); original.navigate({ tab: 'developer' }); original.notice(notice); } };
  const { route, user, navigate, materials, targets, jobs, busy, act, notice, onTask } = context;
  const tab = route.tab;
  return <>
    {tab === 'accounts' && user.role === 'manager' && <AccountManagement/>}
    {tab === 'catalog' && <ApplicationCatalog applications={installedApplications} onSelect={navigate}/>}
    {tab === 'resources' && <ResourceCenter onModels={() => navigate({ tab: 'models', modelReturn: 'resources' })} onConnections={() => navigate({ tab: 'connections' })} onBack={() => navigate({ tab: 'catalog' })}/>}
    {tab === 'models' && <ModelSettings key={`ModelSettings:${user.id}`} ownerId={user.id} onBack={() => navigate({ tab: route.modelReturn ?? 'catalog' })} onCredentials={() => navigate({ tab: 'connections' })}/>}
    {tab === 'developer' && <section><div className="page-heading"><div><h1>开发者装配</h1><p>高级材料与应用契约验证。</p></div></div><ApplicationComposer key={seed?.key ?? 'ordinary'} seed={seed} onSchedule={plan => { setSchedule({ planId: plan.id, planFingerprint: plan.fingerprint, goal: plan.normalizedGoal }); navigate({ tab: 'schedules' }); }} user={user} busy={busy} act={act} materials={materials} targets={targets} onCreated={id => { onTask(id); notice('创建请求已确认。请在任务记录中查看进度与结果。'); }}/></section>}
    {tab === 'tasks' && <TaskWorkspace context={context}/>}
    {tab === 'schedules' && <><ScheduleDiagnostics key={`diagnostics:${user.id}`} ownerId={user.id} api={api.scheduleDiagnostics}/><SchedulesPanel key={`SchedulesPanel:${user.id}`} ownerId={user.id} canManage={!!user} seed={schedule} api={api.schedules} disabled={!!busy} onTask={onTask}/></>}
    {tab === 'storage' && <StoragePanel key={`StoragePanel:${user.id}`} ownerId={user.id} busy={busy} act={act} onNotice={notice}/>}
    {tab === 'connections' && <ConnectionsPanel user={user} jobs={jobs} busy={busy} act={act} onNotice={notice} onModels={() => navigate({ tab: 'models', modelReturn: 'connections' })} onBack={() => navigate({ tab: 'catalog' })} remoteServices={(refresh, onChanged) => <PersonalRemotes key={`${user.id}:${refresh}`} user={user} jobs={jobs} onChanged={onChanged}/>}/>}
    {tab === 'materials' && <MaterialGovernancePanel user={user} materials={materials} busy={busy} act={act} onNotice={notice}/>}
    {tab === 'applications' && <ApplicationGovernance user={user} materials={materials} busy={busy} act={act} onNotice={notice}/>}
    {tab === 'reviews' && <PlanReviews ownerId={user.id} busy={busy} act={act}/>}
  </>;
}
