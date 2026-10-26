import App, { Workspace, type WorkspaceSessionProps } from './App.js';
import { Pages } from './composition.js';
import { ResearchWorkbench } from './apps/research/ResearchWorkspace.js';
import { clearApplicationContext, routePointer, workspaceTabs, type WorkspaceNavigation } from './workspaceNavigation.js';

const applications = [{ id: 'research', name: 'AutoResearch', description: '持续研究项目、目标约定、实验与证据。', entry: { tab: 'research', project: '', researchView: '', researchTab: '', researchSetup: '', researchQASetup: '', researchPeer: '', researchQuestion: '', researchAssociation: '', researchDelivery: '', modelReturn: '' } }];
export const researchNavigation: WorkspaceNavigation = {
  tabs: { ...workspaceTabs, research: 'AutoResearch' }, applicationTabs: ['research'],
  modelReturns: ['catalog', 'resources', 'connections', 'research'],
  queryKeys: ['project', 'researchView', 'researchTab', 'researchSetup', 'researchQASetup', 'researchPeer', 'researchQuestion', 'researchAssociation', 'researchDelivery'],
  readQuery: url => ({ researchAssociation: routePointer(url.searchParams.get('researchAssociation')), researchDelivery: routePointer(url.searchParams.get('researchDelivery')), researchQASetup: routePointer(url.searchParams.get('researchQASetup')), researchPeer: routePointer(url.searchParams.get('researchPeer')), researchQuestion: routePointer(url.searchParams.get('researchQuestion')), researchSetup: routePointer(url.searchParams.get('researchSetup')), project: routePointer(url.searchParams.get('project')), researchView: ['team', 'assistant'].includes(url.searchParams.get('researchView') ?? '') ? url.searchParams.get('researchView')! : '', researchTab: ['experiments', 'evidence', 'delivery'].includes(url.searchParams.get('researchTab') ?? '') ? url.searchParams.get('researchTab')! : '' }),
};
export function ResearchSession(props: WorkspaceSessionProps) {
  return <Workspace {...props} navigation={researchNavigation} applicationView={context => context.route.tab === 'research'
    ? <ResearchWorkbench key={context.user.id} user={context.user} route={context.route} navigate={patch => context.navigate(patch.tab === 'catalog'
      ? { ...clearApplicationContext(researchNavigation), ...patch, modelReturn: undefined }
      : patch.tab && patch.tab !== 'research' ? { ...patch, modelReturn: 'research' } : patch)} onLogout={props.logout} sessionBusy={props.sessionBusy} sessionError={props.sessionError}/>
    : undefined}>{context => <Pages context={context} applications={applications}/>}</Workspace>;
}
export default function ResearchApp() { return <App workspace={ResearchSession}/>; }
