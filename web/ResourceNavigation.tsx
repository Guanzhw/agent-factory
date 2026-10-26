import type { ResourceSection } from './workspaceNavigation.js';
import './resource-workspace.css';

export function ResourceNavigation({ active, onModels, onConnections }: {
  active: 'models' | ResourceSection; onModels: () => void; onConnections: (section: ResourceSection) => void;
}) {
  const sections: readonly [ResourceSection, string][] = [['servers', '服务器'], ['tools', '工具'], ['credentials', '凭据'], ['remotes', '远程服务'], ['advanced', '高级记录']];
  return <nav className="resource-navigation" aria-label="资源分类">
    <button type="button" aria-current={active === 'models' ? 'page' : undefined} onClick={onModels}>模型</button>
    {sections.map(([section, label]) => <button type="button" key={section} aria-current={active === section ? 'page' : undefined} onClick={() => onConnections(section)}>{label}</button>)}
  </nav>;
}
