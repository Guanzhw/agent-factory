import type { WorkspaceContext } from './App.js';
import { AccountManagement } from './AccountManagement.js';
import { ResourceCenter } from './ResourceCenter.js';
import { ModelSettings } from './ModelSettings.js';
import { ConnectionsPanel } from './ConnectionsPanel.js';
import type { ConnectionResource } from './workspaceNavigation.js';

export function Pages({ context, resourceReturn }: { context: WorkspaceContext; resourceReturn: { label: string; onBack: () => void } }) {
  const { route, user, navigate } = context;
  return <>
    {route.tab === 'accounts' && user.role === 'manager' && <AccountManagement/>}
    {route.tab === 'resources' && <ResourceCenter onModels={() => navigate({ tab: 'models' })} onConnections={resource => navigate({ tab: 'connections', resource })} onBack={resourceReturn.onBack} applicationLabel={resourceReturn.label}/>}
    {route.tab === 'models' && <ModelSettings key={user.id} ownerId={user.id} returnLabel={`返回${resourceReturn.label}`} continueLabel={`继续${resourceReturn.label}`} onBack={resourceReturn.onBack} onCredentials={() => navigate({ tab: 'connections', resource: 'credentials' })}/>}
    {route.tab === 'connections' && <ConnectionsPanel user={user} resource={route.resource as ConnectionResource | undefined} onSelectResource={resource => navigate({ resource })} onModels={() => navigate({ tab: 'models' })} onBack={resourceReturn.onBack}/>}
  </>;
}
