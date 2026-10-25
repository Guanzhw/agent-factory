import App, { Workspace, type WorkspaceSessionProps } from './App.js';
import { Pages } from './composition.js';
import { ResourceCenter } from './ResourceCenter.js';
import { ResearchWorkbench } from './apps/research/ResearchWorkspace.js';
import { routePointer, workspaceTabs, type WorkspaceNavigation } from './workspaceNavigation.js';

const applications = [{ id: 'research', name: 'AutoResearch', description: '持续研究项目、目标约定、实验与证据。', entry: { tab: 'research', project: '', researchView: '', researchTab: '', researchSetup: '', researchQASetup: '', researchPeer: '', researchQuestion: '', modelReturn: '' } }];
export const researchNavigation: WorkspaceNavigation = {
  tabs: { ...workspaceTabs, research: 'AutoResearch' }, applicationTabs: ['research'],
  modelReturns: ['catalog', 'resources', 'connections', 'research'],
  queryKeys: ['project', 'researchView', 'researchTab', 'researchSetup', 'researchQASetup', 'researchPeer', 'researchQuestion'],
  readQuery: url => ({ researchQASetup: routePointer(url.searchParams.get('researchQASetup')), researchPeer: routePointer(url.searchParams.get('researchPeer')), researchQuestion: routePointer(url.searchParams.get('researchQuestion')), researchSetup: routePointer(url.searchParams.get('researchSetup')), project: routePointer(url.searchParams.get('project')), researchView: ['team', 'assistant'].includes(url.searchParams.get('researchView') ?? '') ? url.searchParams.get('researchView')! : '', researchTab: ['experiments', 'evidence'].includes(url.searchParams.get('researchTab') ?? '') ? url.searchParams.get('researchTab')! : '' }),
};
function ResearchSession(props: WorkspaceSessionProps) {
  return <Workspace {...props} navigation={researchNavigation} applicationView={context => context.route.tab === 'research'
    ? <ResearchWorkbench key={context.user.id} user={context.user} route={context.route} navigate={context.navigate} onLogout={props.logout} sessionBusy={props.sessionBusy} sessionError={props.sessionError}/>
    : undefined}>{context => context.route.tab === 'resources' && context.route.modelReturn === 'research'
      ? <ResourceCenter applicationLabel="AutoResearch" onModels={() => context.navigate({ tab: 'models', modelReturn: 'research' })} onConnections={() => context.navigate({ tab: 'connections', modelReturn: 'research' })} onBack={() => context.navigate({ tab: 'research', modelReturn: '' })}/>
      : <Pages context={context.route.modelReturn === 'research' && ['models', 'connections'].includes(context.route.tab) ? { ...context, navigate: patch => context.navigate(patch.tab === 'catalog' || patch.tab === 'research' ? { ...patch, tab: 'research', modelReturn: '' } : { ...patch, modelReturn: 'research' }) } : context} applications={applications}/>}</Workspace>;
}
export default function ResearchApp() { return <App workspace={ResearchSession}/>; }
