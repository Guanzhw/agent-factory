import App, { Workspace, type WorkspaceSessionProps } from './App.js';
import { Pages } from './composition.js';
import { ResourceCenter } from './ResourceCenter.js';
import { ResearchDemo } from './apps/research-demo/ResearchDemo.js';
import { routePointer, workspaceTabs, type WorkspaceNavigation } from './workspaceNavigation.js';

const applications = [{ id: 'research-demo', name: 'AutoResearch', description: '研究工作台 · 可点击演示，使用合成数据。', entry: { tab: 'research', project: '', researchView: '', researchTab: '', modelReturn: '' } }];
export const demoNavigation: WorkspaceNavigation = {
  tabs: { ...workspaceTabs, research: 'AutoResearch' }, applicationTabs: ['research'],
  modelReturns: ['catalog', 'resources', 'connections', 'research'],
  queryKeys: ['project', 'researchView', 'researchTab'],
  readQuery: url => ({ project: routePointer(url.searchParams.get('project')), researchView: url.searchParams.get('researchView') === 'team' ? 'team' : '', researchTab: ['experiments', 'evidence'].includes(url.searchParams.get('researchTab') ?? '') ? url.searchParams.get('researchTab')! : '' }),
};
function DemoSession(props: WorkspaceSessionProps) {
  return <Workspace {...props} navigation={demoNavigation} applicationView={context => context.route.tab === 'research'
    ? <ResearchDemo key={context.user.id} user={context.user} route={context.route} navigate={context.navigate} onLogout={props.logout} sessionBusy={props.sessionBusy} sessionError={props.sessionError}/>
    : undefined}>{context => context.route.tab === 'resources' && context.route.modelReturn === 'research'
      ? <ResourceCenter applicationLabel="AutoResearch" onModels={() => context.navigate({ tab: 'models', modelReturn: 'research' })} onConnections={() => context.navigate({ tab: 'connections', modelReturn: 'research' })} onBack={() => context.navigate({ tab: 'research', project: '', researchView: '', researchTab: '', modelReturn: '' })}/>
      : <Pages context={context.route.modelReturn === 'research' && ['models', 'connections'].includes(context.route.tab) ? { ...context, navigate: patch => context.navigate(patch.tab === 'catalog' || patch.tab === 'research' ? { ...patch, tab: 'research', modelReturn: '', project: '', researchView: '', researchTab: '' } : { ...patch, modelReturn: 'research' }) } : context} applications={applications}/>}</Workspace>;
}
export default function ResearchDemoApp() { return <App workspace={DemoSession}/>; }
