export function ResourceCenter({ onModels, onConnections, onResearch }: {
  onModels: () => void; onConnections: () => void; onResearch: () => void;
}) {
  return <section aria-labelledby="resources-title">
    <div className="page-heading"><div><p className="quiet">开始前的准备</p><h1 id="resources-title">我的资源</h1><p>接入自己的模型与运行环境，再回到应用提出研究目标。</p></div><button className="secondary" onClick={onResearch}>返回 OpenResearch</button></div>
    <div className="or-catalog-grid">
      <article className="or-catalog-card"><span className="quiet">1 · 模型</span><h2>我的模型/API</h2><p>设置默认模型与密钥，供平台环境和自助接入的服务器使用。已有远端服务沿用其自身模型设置。</p><button className="primary" onClick={onModels}>设置我的模型/API</button></article>
      <article className="or-catalog-card"><span className="quiet">2 · 运行环境</span><h2>我的服务器与连接</h2><p>接入自己的 SSH 服务器、检查依赖，或管理已有远端连接。使用平台环境时可直接回到 OpenResearch 选择。</p><button className="secondary" onClick={onConnections}>管理服务器与连接</button></article>
    </div>
    <p className="resource-guidance">接入资源只保存或检查设置。恢复环境、创建研究或发送目标，都需要在应用中明确发起。</p>
  </section>;
}
