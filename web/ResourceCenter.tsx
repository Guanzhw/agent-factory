import { IconArrowRight, IconCpu, IconKey, IconServer, IconTools, IconWorld } from '@tabler/icons-react';
import type { ResourceSection } from './workspaceNavigation.js';
import './resource-workspace.css';

export function ResourceCenter({ onModels, onConnections, onBack, applicationLabel = '应用' }: {
  onModels: () => void; onConnections: (section: ResourceSection) => void; onBack: () => void; applicationLabel?: string;
}) {
  const resources = [
    { name: '模型与 API', description: '设置默认模型，管理模型端点与使用的凭据。', icon: IconCpu, action: onModels, label: '设置模型' },
    { name: '服务器', description: '接入自己的 Linux 服务器，分别检查连接和允许执行。', icon: IconServer, action: () => onConnections('servers'), label: '管理服务器' },
    { name: '工具', description: '配置 CLI、MCP 工具及其连接，按需共享给团队。', icon: IconTools, action: () => onConnections('tools'), label: '管理工具' },
    { name: '凭据', description: '保存、轮换或撤销个人凭据，秘密不会向团队成员公开。', icon: IconKey, action: () => onConnections('credentials'), label: '管理凭据' },
    { name: '远程服务', description: '管理已有远程服务的目标、验证与连接授权。', icon: IconWorld, action: () => onConnections('remotes'), label: '管理远程服务' },
  ];
  return <section className="resource-workspace" aria-labelledby="resources-title">
    <div className="page-heading"><div><h1 id="resources-title">我的资源</h1><p>按需配置，再回到应用开始工作。</p></div><button className="secondary" onClick={onBack}>返回 {applicationLabel}</button></div>
    <div className="resource-catalog">{resources.map(({ name, description, icon: Icon, action, label }) => <article className="resource-catalog-item" key={name}>
      <Icon className="resource-icon" size={24} stroke={1.7} aria-hidden="true"/>
      <div><h2>{name}</h2><p>{description}</p></div>
      <button className="text-button" onClick={action}>{label}<IconArrowRight size={17} aria-hidden="true"/></button>
    </article>)}</div>
    <div className="resource-advanced-link"><div><h2>高级资源记录</h2><p>绑定已登记资源，查看连接引用和执行租约。</p></div><button className="text-button" onClick={() => onConnections('advanced')}>查看高级记录<IconArrowRight size={17} aria-hidden="true"/></button></div>
    <p className="resource-guidance">配置和连接检查不会启动任务。执行工作由你在应用中明确发起。</p>
  </section>;
}
