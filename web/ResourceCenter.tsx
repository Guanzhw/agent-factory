import type { ConnectionResource } from './workspaceNavigation.js';

export function ResourceCenter({ onModels, onConnections, onBack, applicationLabel = '应用' }: {
  onModels: () => void; onConnections: (resource: ConnectionResource) => void; onBack: () => void; applicationLabel?: string;
}) {
  return <section aria-labelledby="resources-title">
    <div className="page-heading"><div><h1 id="resources-title">我的资源</h1><p>按需要接入模型、工具或运行环境。保存后回到应用继续。</p></div><button className="secondary" onClick={onBack}>返回 {applicationLabel}</button></div>
    <div className="resource-catalog-grid">
      <article className="resource-catalog-card"><h2>模型与 API</h2><p>选择助手使用的模型，管理默认项、输出额度和密钥引用。</p><button className="primary" onClick={onModels}>设置我的模型/API</button></article>
      <article className="resource-catalog-card"><h2>我的服务器</h2><p>接入自己的 SSH 主机，检查工作目录后启用。</p><button className="secondary" onClick={() => onConnections('servers')}>管理服务器</button></article>
      <article className="resource-catalog-card"><h2>工具</h2><p>接入已支持的 CLI 和 MCP 工具，选择可用身份。</p><button className="secondary" onClick={() => onConnections('tools')}>管理工具</button></article>
      <article className="resource-catalog-card"><h2>远程服务</h2><p>连接已有的研究或执行服务，核对目标后绑定使用。</p><button className="secondary" onClick={() => onConnections('remotes')}>管理远程服务</button></article>
      <article className="resource-catalog-card"><h2>凭据</h2><p>查看或更换已保存的身份凭据，密钥不会显示在共享资料中。</p><button className="secondary" onClick={() => onConnections('credentials')}>管理凭据</button></article>
    </div>
    <p className="resource-guidance">接入资源只保存或检查设置。恢复环境、创建任务或发送目标，仍需在应用中发起。</p>
    <button className="text-button" onClick={() => onConnections('records')}>查看连接绑定与执行记录</button>
  </section>;
}
