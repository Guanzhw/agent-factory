import { useState } from 'react';
import { PersonalCredentials } from './PersonalCredentials.js';
import { PersonalSSHServers } from './PersonalSSHServers.js';
import { PersonalToolConnections } from './PersonalToolConnections.js';
import { connectionResources, type ConnectionResource } from './workspaceNavigation.js';
import type { User } from './models.js';

const labels: Record<ConnectionResource, string> = { servers: '服务器', tools: '工具', credentials: '凭据' };
export function ConnectionsPanel({ user, resource = 'servers', onSelectResource, onModels, onBack }: {
  user: User; resource?: ConnectionResource; onSelectResource: (resource: ConnectionResource) => void; onModels: () => void; onBack: () => void;
}) {
  const [revision, setRevision] = useState(0);
  const changed = () => setRevision(value => value + 1);
  return <section>
    <div className="page-heading"><h1>设置 · {labels[resource]}</h1><button className="secondary" onClick={onBack}>返回对话</button></div>
    <nav className="resource-tabs" aria-label="连接设置">{connectionResources.map(value => <button key={value} aria-current={resource === value ? 'page' : undefined} onClick={() => onSelectResource(value)}>{labels[value]}</button>)}</nav>
    {resource === 'servers' && <PersonalSSHServers ownerId={user.id} revision={revision} onChanged={changed}/>}
    {resource === 'tools' && <PersonalToolConnections ownerId={user.id} revision={revision} onChanged={changed}/>}
    {resource === 'credentials' && <PersonalCredentials ownerId={user.id} revision={revision} onChanged={changed} onModels={onModels}/>}
  </section>;
}
