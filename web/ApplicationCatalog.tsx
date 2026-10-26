import './ApplicationCatalog.css';
import { IconArrowRight, IconFileText } from '@tabler/icons-react';

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
      <h1 id="application-catalog-title">应用</h1>
      <p>选择应用，开始工作。</p>
    </div></div>
    {applications.length ? <div className="application-catalog-grid">
      {applications.map(application => <article className="application-card" key={application.id}>
        <span className="application-icon" aria-hidden="true"><IconFileText size={36}/></span>
        <div className="application-content"><h2>{application.name}</h2>
        <p>{application.description}</p>
        <button type="button" className="primary" onClick={() => onSelect(application.entry)}>进入 {application.name}<IconArrowRight size={20} aria-hidden="true"/></button></div>
      </article>)}
    </div> : <p className="application-catalog-empty">暂无已接入的应用。</p>}
  </section>;
}
