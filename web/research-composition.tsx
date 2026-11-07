import { useEffect } from 'react';
import App, { Workspace, type WorkspaceSessionProps } from './App.js';
import { Pages } from './composition.js';
import { ResearchWorkbench } from './apps/research/ResearchWorkspace.js';
import { clearSessionDrafts } from './apps/research/researchSessionStorage.js';
import { authEpoch } from './browserAuth.js';
import { routePointer, workspaceTabs, type WorkspaceNavigation } from './workspaceNavigation.js';

export const researchNavigation: WorkspaceNavigation = {
  homeTab: 'research',
  tabs: { ...workspaceTabs, research: 'AutoResearch' },
  queryKeys: ['project', 'researchView', 'researchSession', 'researchPeer', 'researchQuestion', 'researchAssociation'],
  readQuery: url => ({ researchSession: routePointer(url.searchParams.get('researchSession')), researchAssociation: routePointer(url.searchParams.get('researchAssociation')), researchPeer: routePointer(url.searchParams.get('researchPeer')), researchQuestion: routePointer(url.searchParams.get('researchQuestion')), project: routePointer(url.searchParams.get('project')), researchView: ['team', 'assistant', 'history', 'sessions'].includes(url.searchParams.get('researchView') ?? '') ? url.searchParams.get('researchView')! : '' }),
};
function ResearchSession(props: WorkspaceSessionProps) {
  useEffect(() => {
    const sessionEpoch = authEpoch();
    // StrictMode and ordinary view remounts are not logout. App invalidates the
    // auth epoch before unmounting a confirmed logout or expired identity.
    return () => { if (authEpoch() !== sessionEpoch) clearSessionDrafts(props.user.id); };
  }, [props.user.id]);
  return <Workspace {...props} navigation={researchNavigation} applicationView={context =>
    <ResearchWorkbench key={context.user.id} user={context.user} route={context.route} navigate={context.navigate} onTab={context.selectTab}
      onLogout={props.logout} sessionBusy={props.sessionBusy} sessionError={props.sessionError}
      workspaceContent={context.route.tab === 'research' ? undefined : <>{context.feedback}<Pages context={context}
        resourceReturn={{ label: '对话', onBack: () => context.navigate({ tab: 'research' }) }}/></>}/>
  }/>;
}
export default function ResearchApp() { return <App workspace={ResearchSession}/>; }
