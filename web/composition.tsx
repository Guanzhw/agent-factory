/** Static deployment assembly. Applications do not install code through declarations. */
import { useState } from 'react';
import App, { Workspace as WorkspaceShell, type WorkspaceSessionProps, type WorkspaceContext } from './App.js';
import { api } from './api.js';
import { ApplicationComposer, type ComposerSeed } from './ApplicationComposer.js';
import type { InstalledApplication } from './ApplicationCatalog.js';
import { WorkspaceHome } from './WorkspaceHome.js';
import { ResourceNavigation } from './ResourceNavigation.js';
import { resourceSection, type ResourceSection } from './workspaceNavigation.js';
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
export function Pages({ context: original, applications = installedApplications }: { context: WorkspaceContext; applications?: readonly InstalledApplication[] }) {
  const [seed, setSeed] = useState<ComposerSeed>();
  const [schedule, setSchedule] = useState<{ planId: string; planFingerprint: string; goal: string }>();
  const context: WorkspaceContext = { ...original, onCompose: (next, notice) => { setSeed(next); original.navigate({ tab: 'developer' }); original.notice(notice); } };
  const { route, user, navigate, materials, targets, jobs, busy, act, notice, onTask } = context;
  const tab = route.tab;
  const source = context.applicationSource;
  const onModels = () => {
    if (tab === 'models') return;
    navigate({ tab: 'models', modelReturn: source?.tab ?? (tab === 'connections' ? 'connections' : 'resources') });
  };
  const onConnections = (resource: ResourceSection) => navigate({ tab: 'connections', resource, modelReturn: source?.tab });
  const backToApplication = () => navigate({ tab: source?.tab ?? 'catalog', modelReturn: undefined, resource: undefined });
  const backToResources = () => source ? backToApplication() : navigate({ tab: 'resources', modelReturn: undefined });
  const modelBack = () => source ? backToApplication() : navigate({ tab: route.modelReturn ?? 'resources', modelReturn: undefined });
  const backLabel = source ? `返回 ${source.label}` : '返回我的资源';
  const resourceNavigation = <ResourceNavigation active={tab === 'models' ? 'models' : resourceSection(route.resource)} onModels={onModels} onConnections={onConnections}/>;
  return <>
    {tab === 'accounts' && user.role === 'manager' && <AccountManagement/>}
    {tab === 'catalog' && <WorkspaceHome context={context} applications={applications}/>}
    {tab === 'resources' && <ResourceCenter onModels={onModels} onConnections={onConnections} onBack={backToApplication} applicationLabel={source?.label ?? '应用'}/>}
    {tab === 'models' && <ModelSettings key={`ModelSettings:${user.id}`} ownerId={user.id} onBack={modelBack} backLabel={source ? backLabel : route.modelReturn === 'catalog' ? '返回应用' : route.modelReturn === 'connections' ? '返回连接设置' : backLabel} navigation={resourceNavigation} onCredentials={() => onConnections('credentials')}/>}
    {tab === 'developer' && <section><div className="page-heading"><div><h1>开发者装配</h1><p>高级材料与应用契约验证。</p></div></div><ApplicationComposer key={seed?.key ?? 'ordinary'} seed={seed} onSchedule={plan => { setSchedule({ planId: plan.id, planFingerprint: plan.fingerprint, goal: plan.normalizedGoal }); navigate({ tab: 'schedules' }); }} user={user} busy={busy} act={act} materials={materials} targets={targets} onCreated={id => { onTask(id); notice('创建请求已确认。请在任务记录中查看进度与结果。'); }}/></section>}
    {tab === 'tasks' && <TaskWorkspace context={context}/>}
    {tab === 'schedules' && <><ScheduleDiagnostics key={`diagnostics:${user.id}`} ownerId={user.id} api={api.scheduleDiagnostics}/><SchedulesPanel key={`SchedulesPanel:${user.id}`} ownerId={user.id} canManage={!!user} seed={schedule} api={api.schedules} disabled={!!busy} onTask={onTask}/></>}
    {tab === 'storage' && <StoragePanel key={`StoragePanel:${user.id}`} ownerId={user.id} busy={busy} act={act} onNotice={notice}/>}
    {tab === 'connections' && <ConnectionsPanel user={user} jobs={jobs} busy={busy} act={act} onNotice={notice} section={resourceSection(route.resource)} navigation={resourceNavigation} onModels={onModels} onBack={backToResources} backLabel={backLabel} remoteServices={(refresh, onChanged) => <PersonalRemotes key={`${user.id}:${refresh}`} user={user} jobs={jobs} onChanged={onChanged}/>}/>}
    {tab === 'materials' && <MaterialGovernancePanel user={user} materials={materials} busy={busy} act={act} onNotice={notice}/>}
    {tab === 'applications' && <ApplicationGovernance user={user} materials={materials} busy={busy} act={act} onNotice={notice}/>}
    {tab === 'reviews' && <PlanReviews ownerId={user.id} busy={busy} act={act}/>}
  </>;
}
