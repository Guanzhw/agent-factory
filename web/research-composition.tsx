import App, { Workspace, type WorkspaceSessionProps } from './App.js';
import { Pages } from './composition.js';
import { ResearchWorkspace } from './apps/research/ResearchWorkspace.js';
import { routePointer, workspaceTabs, type WorkspaceNavigation } from './workspaceNavigation.js';

const applications = [{ id: 'research', name: '研究助手', description: '持续研究项目、目标约定与证据。', entry: { tab: 'research' } }];
const navigation: WorkspaceNavigation = { tabs: { ...workspaceTabs, research: '研究助手' },
  applicationTabs: ['research'], modelReturns: ['catalog', 'resources', 'connections', 'research'],
  queryKeys: ['project'], readQuery: url => ({ project: routePointer(url.searchParams.get('project')) }) };
function ResearchSession(props: WorkspaceSessionProps) {
  return <Workspace {...props} navigation={navigation}>{context => context.route.tab === 'research'
    ? <ResearchWorkspace key={context.user.id} ownerId={context.user.id} projectId={context.route.project}
        onProject={project => context.navigate({ tab: 'research', project: project ?? '' })}
        onResources={() => context.navigate({ tab: 'resources' })}/>
    : <Pages context={context} applications={applications}/>}</Workspace>;
}
export default function ResearchApp() { return <App workspace={ResearchSession}/>; }
