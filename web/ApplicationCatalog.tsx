import './ApplicationCatalog.css';

/** Trusted, static composition data; entries only navigate to installed UI. */
export interface InstalledApplication {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly entry: { readonly tab: string };
}

export function ApplicationCatalog({ applications, onSelect }: {
  applications: readonly InstalledApplication[];
  onSelect: (entry: InstalledApplication['entry']) => void;
}) {
  return <section className="application-catalog" aria-labelledby="application-catalog-title">
    <div className="page-heading"><div>
      <h1 id="application-catalog-title">应用目录</h1>
      <p>选择应用，开始工作。</p>
    </div></div>
    {applications.length ? <div className="application-catalog-grid">
      {applications.map(application => <article className="application-card" key={application.id}>
        <h2>{application.name}</h2>
        <p>{application.description}</p>
        <button type="button" className="primary" onClick={() => onSelect(application.entry)}>进入 {application.name}</button>
      </article>)}
    </div> : <p className="application-catalog-empty">暂无已接入的应用。</p>}
  </section>;
}
