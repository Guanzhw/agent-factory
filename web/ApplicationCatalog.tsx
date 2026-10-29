import { useEffect, useState, type ReactNode } from 'react';
import { api } from './api.js';
import type { ApplicationVersion, FactoryApplication } from './models.js';
import './ApplicationCatalog.css';

/** Trusted, static composition data; entries only navigate to installed UI. */
export interface InstalledApplication {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly entry: { readonly tab: string };
}

export function ApplicationCatalog({ applications, onSelect, onTemplates }: {
  applications: readonly InstalledApplication[];
  onSelect: (entry: InstalledApplication['entry']) => void;
  onTemplates?: () => void;
}) {
  return <section className="application-catalog" aria-labelledby="application-catalog-title">
    <div className="page-heading"><div>
      <h1 id="application-catalog-title">应用目录</h1>
      <p>选择应用，开始工作。</p>
    </div>{onTemplates && <button className="secondary" onClick={onTemplates}>任务模板</button>}</div>
    {applications.length ? <div className="application-catalog-grid">
      {applications.map(application => <article className="application-card" key={application.id}>
        <h2>{application.name}</h2>
        <p>{application.description}</p>
        <button type="button" className="primary" onClick={() => onSelect(application.entry)}>进入 {application.name}</button>
      </article>)}
    </div> : <p className="application-catalog-empty">暂无已接入的应用。</p>}
  </section>;
}

export function TemplateCatalog({ id, version, creating, onSelect, onCreate, onBack, onApplications, onAuthor, renderComposer }: {
  id?: string; version?: number; creating: boolean;
  onSelect: (application: FactoryApplication) => void; onCreate: () => void; onBack: () => void;
  onApplications: () => void; onAuthor: () => void;
  renderComposer: (application?: FactoryApplication) => ReactNode;
}) {
  const [items, setItems] = useState<FactoryApplication[]>([]);
  const [detail, setDetail] = useState<ApplicationVersion>();
  const [cursor, setCursor] = useState<string>();
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); setDetail(undefined);
    if (id && version) {
      void api.inspectApplication(id, version, controller.signal).then(value => {
        if (!controller.signal.aborted) setDetail(value);
      }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '无法读取模板。'); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    } else {
      void api.templateCatalog(cursor, controller.signal).then(page => {
        if (controller.signal.aborted) return;
        setItems(current => cursor ? [...current, ...page.items] : page.items); setNext(page.nextCursor);
      }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '无法读取任务模板。'); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }
    return () => controller.abort();
  }, [id, version, cursor, refresh]);
  const available = detail?.governance.state === 'published' && detail.governance.entry_kind === 'template' && !detail.governance.bootstrap;
  return <section className="application-catalog" aria-labelledby="template-catalog-title">
    <div className="page-heading"><div><h1 id="template-catalog-title">{creating ? '从模板创建任务' : id ? detail?.application.name ?? '模板详情' : '任务模板'}</h1>
      <p>模板提供任务方式；填写本次目标后，先预览再决定是否开始。已接入的独立应用可直接进入。</p></div>
      <button className="secondary" onClick={id || creating ? () => { setCursor(undefined); setItems([]); onBack(); } : onApplications}>{id || creating ? '返回模板列表' : '返回应用'}</button></div>
    {error && <div role="alert" className="error-message">{error}<button className="text-button" onClick={() => setRefresh(value => value + 1)}>重新读取模板</button></div>}
    {loading && <p role="status">正在读取模板…</p>}
    {!id && !creating && <>
      {!loading && !error && !items.length && <div className="state-note"><h2>还没有已发布的任务模板</h2><p>可以先使用已接入的应用；需要重复使用的任务时，再由作者发布模板。</p><div className="button-row"><button className="primary" onClick={onApplications}>查看应用</button><button className="secondary" onClick={onAuthor}>前往模板创作</button></div></div>}
      {items.length > 0 && <><div className="template-catalog-intro"><p>选择模板查看用途和需要填写的内容；也可让系统根据目标自动匹配。</p><button className="secondary" onClick={onCreate}>根据目标自动匹配</button></div><div className="application-catalog-grid">{items.map(item => <article className="application-card" key={`${item.id}:${item.version}`}><h2>{item.name}</h2><span className="quiet">版本 {item.version}</span><p>{item.description}</p><button className="primary" onClick={() => onSelect(item)}>查看模板</button></article>)}</div></>}
      {next && <button className="secondary template-more" disabled={loading || !!error} onClick={() => setCursor(next)}>更多模板</button>}
    </>}
    {detail && !creating && <article className="template-detail"><p>{detail.application.description}</p><p className="quiet">固定版本 {detail.application.version} · 资源将在预览时核对</p>
      <h2>可以完成什么</h2>{Object.entries(detail.application.modes).map(([name, mode]) => <section key={name}><h3>{name === detail.application.defaultMode ? `${name}（默认）` : name}</h3>
        {mode.inputSchema?.description && <p>{mode.inputSchema.description}</p>}
        <dl className="plan-details"><dt>需要填写</dt><dd>{Object.entries(mode.inputSchema?.properties ?? {}).map(([key, field]) => <span className="material-chip" key={key}>{field.title || key}{mode.inputSchema?.required?.includes(key) ? '（必需）' : '（可选）'}</span>)}{!Object.keys(mode.inputSchema?.properties ?? {}).length && '本次任务目标'}</dd><dt>需要的个人资源</dt><dd>{mode.connectionRequirements.map(item => <span className="material-chip" key={item.name}>{item.name}{item.required ? '（必需）' : '（可选）'}</span>)}{!mode.connectionRequirements.length && '无额外连接'}</dd></dl></section>)}
      {available ? <button className="primary" onClick={onCreate}>用此模板创建任务</button> : <p role="status" className="state-note">这个版本当前不提供普通模板入口。已有应用与任务仍从原入口使用。</p>}
    </article>}
    {creating && (!id || available) && !loading && !error && renderComposer(detail?.application)}
    {creating && detail && !available && <p role="status" className="state-note">这个版本当前不提供普通模板入口。请返回目录重新选择。</p>}
  </section>;
}
