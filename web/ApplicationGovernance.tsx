import { useEffect, useState } from 'react';
import { api } from './api.js';
import { useCommandKeys } from './commandKeys.js';
import type { ApplicationReview, ApplicationVersion, FactoryApplication, FactoryMaterial, User } from './models.js';

type Act = (name: string, work: () => Promise<void>) => Promise<void>;
const labels: Record<string, string> = { draft: '草稿', published: '已发布', withdrawn: '已撤回', archived: '已归档', pending: '待审查', approved: '已同意', denied: '已拒绝' };
const message = (e: unknown) => e instanceof Error ? e.message : '应用治理状态无法确认。';
const exact = (app: FactoryApplication) => `${app.id}@${app.version}:${app.sha256}`;
function definition(app: FactoryApplication): Record<string, unknown> {
  return { id: app.id, name: app.name, description: app.description, discoveryKeywords: app.discoveryKeywords,
    defaultForDiscovery: app.defaultForDiscovery, defaultMode: app.defaultMode, modes: app.modes };
}
function ApplicationEvidence({ application, materials }: { application: FactoryApplication; materials: FactoryMaterial[] }) {
  return <><p>{application.description}</p><dl className="plan-details"><dt>发现关键词</dt><dd>{application.discoveryKeywords.join('、') || '无'}</dd><dt>默认方式</dt><dd>{application.defaultMode}{application.defaultForDiscovery ? ' · 默认候选' : ''}</dd></dl>{Object.entries(application.modes).map(([mode, scope]) => <details className="technical-detail application-mode-evidence" key={mode} open><summary>方式 {mode} 的完整范围</summary><span>能力 {scope.capabilities.join('、')}</span><span>工具顺序 {scope.toolOrder.join(' → ')}</span><pre>{JSON.stringify({ materialRefs: scope.materialRefs, materialChoices: scope.materialChoices, budget: scope.budget, config: scope.config, connectionRequirements: scope.connectionRequirements }, null, 2)}</pre><div>{scope.materialRefs.map(ref => { const material = materials.find(item => item.id === ref.id && item.version === ref.version && item.sha256 === ref.sha256); return <details className="technical-detail" key={`${ref.id}:${ref.version}`}><summary>{material?.name ?? ref.id} · v{ref.version} 的来源与内容</summary>{material ? <pre>{JSON.stringify({ kind: material.kind, sha256: material.sha256, content: material.content, permissions: material.permissions, dependencies: material.dependencies, license: material.license, origin: material.origin, provenance: material.provenance }, null, 2)}</pre> : <p>目录未提供此精确材料；请先核对材料版本。</p>}</details>; })}</div></details>)}<details className="technical-detail"><summary>不可变应用正文与哈希</summary><span>{exact(application)}</span><pre>{JSON.stringify(application, null, 2)}</pre></details></>;
}

export function ApplicationGovernance({ user, materials, busy, act, onNotice }: { user: User; materials: FactoryMaterial[]; busy: string; act: Act; onNotice: (message: string) => void }) {
  const [versions, setVersions] = useState<ApplicationVersion[]>([]);
  const [reviews, setReviews] = useState<ApplicationReview[]>([]);
  const [active, setActive] = useState<FactoryApplication[]>([]);
  const [allAuthors, setAllAuthors] = useState(false);
  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [source, setSource] = useState<FactoryApplication>();
  const [draft, setDraft] = useState('');
  const [draftError, setDraftError] = useState('');
  const [reason, setReason] = useState('');
  const keys = useCommandKeys(user.id);
  useEffect(() => {
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const [session, defs, pending, apps] = await Promise.all([api.session(controller.signal), api.applicationVersions(allAuthors, controller.signal), api.applicationReviews(allAuthors, controller.signal), api.applications(controller.signal)]);
        if (session.id !== user.id || session.role !== 'manager') throw new Error('当前管理身份无法核对；暂时禁用治理操作。');
        if (controller.signal.aborted) return;
        setVersions(defs); setReviews(pending); setActive(apps); setReady(true); setError('');
      } catch (e) { if (!controller.signal.aborted) { setError(message(e)); setReady(false); } }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 5000);
    }
    void poll(); return () => { controller.abort(); clearTimeout(timer); };
  }, [user.id, allAuthors, refresh]);
  function load(app: FactoryApplication, revise: boolean) {
    const body = definition(app); if (!revise) delete body.id;
    setSource(revise ? app : undefined); setDraft(JSON.stringify(body, null, 2)); setDraftError('');
  }
  async function save() {
    if (!ready) return;
    let body: Record<string, unknown>;
    try { const value: unknown = JSON.parse(draft); if (!value || typeof value !== 'object' || Array.isArray(value) || 'version' in value || 'sha256' in value) throw new Error('请输入应用定义对象；版本和哈希由后端生成。'); body = value as Record<string, unknown>; }
    catch (e) { setDraftError(message(e)); return; }
    setDraftError('');
    await act('draft-application', async () => {
      const key = await keys('draft-application', { definition: body, source: source ? exact(source) : null });
      const saved = source ? await api.reviseApplication(source.id, source.version, body, key.requestId) : await api.draftApplication(body, key.requestId);
      key.acknowledged(); setSource(saved); setDraft(JSON.stringify(definition(saved), null, 2)); setRefresh(n => n + 1);
      onNotice(`应用草稿 v${saved.version} 已保存，尚未发布。`);
    });
  }
  async function requestReview(app: FactoryApplication) {
    if (!ready) return;
    await act('application-publication-request', async () => { const key = await keys('application-publication-request', { applicationRef: exact(app) }); const review = await api.requestApplicationPublication(app.id, app.version, key.requestId); if (exact(review.application) !== exact(app)) throw new Error('审查回执与所选应用版本不一致。'); setRefresh(n => n + 1); onNotice('发布申请已保存；需要另一位当前管理员审查此精确版本。'); });
  }
  async function decide(review: ApplicationReview, approved: boolean) {
    if (!ready || review.authorId === user.id || review.decision !== 'pending' || review.state !== 'draft') return;
    await act('application-review-decision', async () => { const key = await keys('application-review-decision', { reviewId: review.id, applicationRef: review.applicationRef, approved }); const saved = await api.decideApplicationReview(review.id, approved, key.requestId); if (saved.id !== review.id || saved.application.sha256 !== review.application.sha256 || saved.decision !== (approved ? 'approved' : 'denied')) throw new Error('应用审查结果未核对。'); key.acknowledged(); setRefresh(n => n + 1); onNotice(approved ? '应用发布审查已同意；任务执行仍需独立授权。' : '应用发布审查已拒绝，原版本与审查证据保留。'); });
  }
  async function retire(item: ApplicationVersion, operation: 'archive' | 'withdraw') {
    if (!ready || !reason.trim() || reason.trim().length > 1000) return;
    await act(`${operation}-application`, async () => { const key = await keys(`${operation}-application`, { applicationRef: exact(item.application), reason: reason.trim() }); const run = operation === 'archive' ? api.archiveApplication : api.withdrawApplication; await run(item.application.id, item.application.version, reason.trim(), key.requestId); key.acknowledged(); setRefresh(n => n + 1); onNotice(operation === 'archive' ? '应用版本已归档，原正文和证据保留。' : '应用版本已撤回，后续装配会重新检查当前状态。'); });
  }
  return <section className="materials-page"><div className="page-heading"><div><h1>应用定义治理</h1><p>维护复用的应用装配范围。草稿、发布审查和临时方案执行分别授权。</p></div><button className="secondary" disabled={!!busy} onClick={() => setRefresh(n => n + 1)}>刷新应用治理</button></div><div className="state-note">应用只能引用已批准材料和已注册适配器。发布必须由另一位当前管理员审查；页面不能自行授予权限或启动真实提供商。</div>{error && <div className="error-message" role="alert">{error}</div>}
    <section className="material-editor"><div className="section-heading"><h2>{source ? `修订 ${source.name} v${source.version}` : '新应用草稿'}</h2><button className="text-button" disabled={!!busy} onClick={() => { setSource(undefined); setDraft(''); setDraftError(''); }}>清空作者草稿</button></div><label>从已批准应用复制<select aria-label="复制应用定义" defaultValue="" disabled={!!busy || !ready} onChange={event => { const item = active.find(app => exact(app) === event.target.value); if (item) load(item, false); }}><option value="">选择定义作为起点</option>{active.map(app => <option key={exact(app)} value={exact(app)}>{app.name} · v{app.version}</option>)}</select></label><form onSubmit={event => { event.preventDefault(); void save(); }}><label htmlFor="application-definition-json">应用定义 JSON</label><textarea id="application-definition-json" className="code-input" rows={14} maxLength={131072} value={draft} disabled={!!busy || !ready} onChange={event => { setDraft(event.target.value); setDraftError(''); }} placeholder="复制一个已批准定义，修改名称、发现关键词、执行方式与精确材料引用。" required/><p className="quiet">只保存结构化定义，不执行输入代码。每种方式固定六类材料、可选槽位、工具顺序、能力、预算和可信连接要求；版本与哈希由服务端生成。</p>{draftError && <div role="alert" className="error-message">{draftError}</div>}<button className="primary" disabled={!!busy || !ready || !draft.trim()}>{busy === 'draft-application' ? '等待草稿确认…' : source ? '保存新的应用版本' : '保存应用草稿'}</button></form></section>
    <div className="section-heading"><h2>应用版本与发布申请</h2><label className="application-admin-toggle"><input type="checkbox" checked={allAuthors} disabled={!!busy} onChange={event => { setAllAuthors(event.target.checked); setReady(false); }}/>查看全部作者（需当前管理员权限）</label></div><label className="retire-reason">归档或撤回原因<textarea aria-label="应用归档撤回原因" rows={2} value={reason} maxLength={1000} disabled={!!busy} onChange={event => setReason(event.target.value)} placeholder="填写具体原因，再选择对应版本的操作。"/></label>
    {versions.map(item => <article className="material-row review-row" key={exact(item.application)}><div className="material-info"><h2>{item.application.name} · v{item.application.version}</h2><p>{labels[item.governance.state]} · 作者 {item.governance.author_id}{item.governance.bootstrap ? ' · 演示启动定义' : ''}</p>{item.governance.reason && <p>状态原因：{item.governance.reason}</p>}<ApplicationEvidence application={item.application} materials={materials}/></div><div className="material-actions"><button className="secondary" disabled={!!busy || !ready} onClick={() => load(item.application, true)}>载入并修订</button>{item.governance.state === 'draft' && <button className="primary" disabled={!!busy || !ready} onClick={() => void requestReview(item.application)}>申请发布此版本</button>}{item.governance.state === 'published' && <button className="secondary danger" disabled={!!busy || !ready || !reason.trim()} onClick={() => void retire(item, 'withdraw')}>撤回此版本</button>}{item.governance.state !== 'archived' && <button className="secondary danger" disabled={!!busy || !ready || !reason.trim()} onClick={() => void retire(item, 'archive')}>归档此版本</button>}</div></article>)}{ready && !versions.length && <p className="list-empty">暂无可见的应用版本。</p>}
    <h2>独立发布审查</h2>{reviews.map(review => <article className="material-row review-row" key={review.id}><div className="material-info"><h2>{review.application.name} · v{review.application.version}</h2><p>{labels[review.decision]} · 作者 {review.authorId} · 当前版本 {labels[review.state]}</p>{review.authorId === user.id && <p className="policy-note">你是作者，不能审查自己的发布申请。请由另一位当前管理员决定。</p>}<ApplicationEvidence application={review.application} materials={materials}/><details className="technical-detail"><summary>审查凭据</summary><span>审查 {review.id}</span><span>审查人 {review.reviewerId ?? '待审查'}</span><span>准确应用 {exact(review.application)}</span></details></div><div className="material-actions"><button className="primary" disabled={!!busy || !ready || review.authorId === user.id || review.decision !== 'pending' || review.state !== 'draft'} onClick={() => void decide(review, true)}>同意发布此版本</button><button className="secondary danger" disabled={!!busy || !ready || review.authorId === user.id || review.decision !== 'pending' || review.state !== 'draft'} onClick={() => void decide(review, false)}>拒绝发布此版本</button></div></article>)}{ready && !reviews.length && <p className="list-empty">暂无可见的应用发布审查。</p>}
  </section>;
}
