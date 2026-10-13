import { useEffect, useRef, useState } from 'react';
import { publicationApi } from './publicationApi.js';
import { api, ApiError } from './api.js';
import { ApplicationTemplateEditor } from './ApplicationTemplateEditor.js';
import { inspectTemplate, templateDefinition } from './applicationTemplateState.js';
import { savedApplicationMatches } from './applicationGovernanceState.js';
import { useCommandKeys } from './commandKeys.js';
import type { ApplicationReview, ApplicationVersion, FactoryApplication, FactoryMaterial, User } from './models.js';

type Act = (name: string, work: () => Promise<void>) => Promise<void>;
const labels: Record<string, string> = { draft: '草稿', published: '已发布', withdrawn: '已撤回', archived: '已归档', pending: '待审查', approved: '已同意', denied: '已拒绝' };
const message = (e: unknown) => e instanceof Error ? e.message : '应用治理状态无法确认。';
const exact = (app: FactoryApplication) => `${app.id}@${app.version}:${app.sha256}`;
function ApplicationEvidence({ application, materials }: { application: FactoryApplication; materials: FactoryMaterial[] }) {
  return <><p>{application.description}</p><dl className="plan-details"><dt>发现关键词</dt><dd>{application.discoveryKeywords.join('、') || '无'}</dd><dt>默认方式</dt><dd>{application.defaultMode}{application.defaultForDiscovery ? ' · 默认候选' : ''}</dd></dl>{Object.entries(application.modes).map(([mode, scope]) => <details className="technical-detail application-mode-evidence" key={mode} open><summary>方式 {mode} 的完整范围</summary><span>能力 {scope.capabilities.join('、')}</span><span>工具顺序 {scope.toolOrder.join(' → ')}</span><pre>{JSON.stringify({ materialRefs: scope.materialRefs, materialChoices: scope.materialChoices, budget: scope.budget, config: scope.config, connectionRequirements: scope.connectionRequirements }, null, 2)}</pre><div>{scope.materialRefs.map(ref => { const material = materials.find(item => item.id === ref.id && item.version === ref.version && item.sha256 === ref.sha256); return <details className="technical-detail" key={`${ref.id}:${ref.version}`}><summary>{material?.name ?? ref.id} · v{ref.version} 的来源与内容</summary>{material ? <pre>{JSON.stringify({ kind: material.kind, sha256: material.sha256, content: material.content, permissions: material.permissions, dependencies: material.dependencies, license: material.license, origin: material.origin, provenance: material.provenance }, null, 2)}</pre> : <p>目录未提供此精确材料；请先核对材料版本。</p>}</details>; })}</div></details>)}<details className="technical-detail"><summary>不可变应用正文与哈希</summary><span>{exact(application)}</span><pre>{JSON.stringify(application, null, 2)}</pre></details></>;
}

export function ApplicationGovernance({ user, materials, busy, act, onNotice }: { user: User; materials: FactoryMaterial[]; busy: string; act: Act; onNotice: (message: string) => void }) {
  const [versions, setVersions] = useState<ApplicationVersion[]>([]);
  const [reviews, setReviews] = useState<ApplicationReview[]>([]);
  const [active, setActive] = useState<FactoryApplication[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const isAdmin = user.role === 'manager';
  const currentOwner = useRef(user.id); currentOwner.current = user.id;
  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [source, setSource] = useState<FactoryApplication>();
  const [draft, setDraft] = useState('');
  const [draftError, setDraftError] = useState('');
  const [reason, setReason] = useState('');
  const keys = useCommandKeys(user.id);
  const [template, setTemplate] = useState('');
  const [advanced, setAdvanced] = useState(false);
  const [pendingSave, setPendingSave] = useState<{ body: Record<string, unknown>; parent?: FactoryApplication; requestId: string; acknowledged: () => void }>();
  let parsed: Record<string, unknown> | undefined;
  try { const value: unknown = JSON.parse(draft); if (value && typeof value === 'object' && !Array.isArray(value)) parsed = value as Record<string, unknown>; } catch { /* Advanced JSON may be incomplete while editing. */ }
  const inspection = inspectTemplate(parsed, materials);
  const locked = !!busy || !!pendingSave;
  async function verifyActor(adminOnly = false) { const session = await api.session(); if (session.id !== user.id || adminOnly && session.role !== 'manager') throw new Error('当前身份或操作权限无法核对，请重新登录。'); }

  useEffect(() => {
    const controller = new AbortController();
    setReady(false); setVersions([]); setReviews([]); setHistoryLoaded(false);
    async function read() {
      try {
        const [session, defs, apps] = await Promise.all([api.session(controller.signal), api.applicationVersions(true, controller.signal), api.applications(controller.signal)]);
        if (session.id !== user.id) throw new Error('当前身份无法核对；请重新登录。');
        if (session.role !== 'manager' && defs.some(item => item.governance.state === 'draft' && item.governance.author_id !== user.id)) throw new Error('应用草稿归属无法核对。');
        if (controller.signal.aborted) return;
        setVersions(defs); setActive(apps); setReady(true); setError('');
      } catch (e) { if (!controller.signal.aborted) { setError(message(e)); setReady(false); } }
    }
    void read(); return () => controller.abort();
  }, [user.id, refresh]);
  async function readHistory() {
    await act('application-publication-history', async () => {
      await verifyActor();
      const records = await api.applicationReviews(isAdmin);
      if (!isAdmin && records.some(item => item.authorId !== user.id)) throw new Error('历史记录归属无法核对。');
      if (currentOwner.current !== user.id) return;
      setReviews(records); setHistoryLoaded(true);
    });
  }
  function load(app: FactoryApplication, revise: boolean) {
    if (locked) return;
    const body = templateDefinition(app, revise ? 'revise' : 'copy');
    setTemplate(revise ? '' : exact(app)); setAdvanced(false);
    setSource(revise ? app : undefined); setDraft(JSON.stringify(body, null, 2)); setDraftError('');
  }
  async function save() {
    if (!ready) return;
    if (!pendingSave && (!parsed || 'version' in parsed || 'sha256' in parsed)) { setDraftError('请输入应用定义对象；版本和哈希由后端生成。'); return; }
    if (!pendingSave && !advanced && (!inspection.guided || inspection.errors.length)) return;
    setDraftError('');
    await act('draft-application', async () => {
      await verifyActor();
      const original = pendingSave ?? { body: structuredClone(parsed!), parent: source, ...await keys('draft-application', { definition: parsed, source: source ? exact(source) : null }) };
      setPendingSave(original);
      try {
        const saved = original.parent ? await api.reviseApplication(original.parent.id, original.parent.version, original.body, original.requestId) : await api.draftApplication(original.body, original.requestId);
        if (!savedApplicationMatches(original.body, original.parent, saved)) throw new Error('保存回执与原定义不一致，请核对并重试原保存。');
        original.acknowledged(); setPendingSave(undefined); setSource(saved); setTemplate(''); setDraft(JSON.stringify(templateDefinition(saved, 'revise'), null, 2)); setRefresh(n => n + 1);
        onNotice(`应用草稿 v${saved.version} 已保存，尚未发布。`);
      } catch (error) {
        if (!pendingSave && error instanceof ApiError && error.status >= 400 && error.status < 500) setPendingSave(undefined);
        setDraftError(message(error)); throw error;
      }
    });
  }
  async function publish(app: FactoryApplication) {
    if (!ready || pendingSave) return;
    await act('publish-application', async () => {
      await verifyActor();
      const key = await keys('publish-application', { applicationRef: exact(app) });
      const saved = await publicationApi.publishApplication(user.id, app.id, app.version, key.requestId);
      if (exact(saved) !== exact(app)) throw new Error('发布回执与所选应用版本不一致。');
      key.acknowledged(); setRefresh(n => n + 1); onNotice(`应用 v${app.version} 已发布。已有任务继续保留原固定版本与个人绑定。`);
    });
  }
  async function retire(item: ApplicationVersion, operation: 'archive' | 'withdraw') {
    if (!isAdmin || !ready || pendingSave || !reason.trim() || reason.trim().length > 1000) return;
    await act(`${operation}-application`, async () => { await verifyActor(true); const key = await keys(`${operation}-application`, { applicationRef: exact(item.application), reason: reason.trim() }); const run = operation === 'archive' ? api.archiveApplication : api.withdrawApplication; await run(item.application.id, item.application.version, reason.trim(), key.requestId); key.acknowledged(); setRefresh(n => n + 1); onNotice(operation === 'archive' ? '应用版本已归档，原正文和证据保留。' : '应用版本已撤回，后续装配会重新检查当前状态。'); });
  }
  return <section className="materials-page"><div className="page-heading"><div><h1>应用管理</h1><p>成员可创建、修订和发布部门共享应用。</p></div><button className="secondary" disabled={locked} onClick={() => setRefresh(n => n + 1)}>刷新应用</button></div><div className="state-note">编辑会保存为新版本。已有任务与个人绑定继续使用原固定版本；使用新版本时重新选择自己的连接。撤回和归档由管理员操作，历史保留。</div>{error && <div className="error-message" role="alert">{error}</div>}
    <section className="material-editor"><div className="section-heading"><h2>{source ? `修订 ${source.name} v${source.version}` : '新应用草稿'}</h2><button className="text-button" disabled={locked} onClick={() => { setSource(undefined); setTemplate(''); setDraft(''); setDraftError(''); }}>清空作者草稿</button></div>
      <label>从已发布应用复制<select aria-label="复制应用定义" value={template} disabled={locked || !ready} onChange={event => { const item = active.find(app => exact(app) === event.target.value); if (item) load(item, false); }}><option value="">选择定义作为起点</option>{active.map(app => <option key={exact(app)} value={exact(app)}>{app.name} · v{app.version}</option>)}</select></label>
      {template && <p className="quiet">复制来源 {template}。保存会创建独立应用，保存后可直接发布。</p>}
      {source && <p className="quiet">修订来源 {exact(source)}。保存会创建新版本，原版本和已有绑定保持不变。</p>}
      <form onSubmit={event => { event.preventDefault(); void save(); }}>
        <label><input type="checkbox" aria-label="高级 JSON 编辑" checked={advanced} disabled={locked} onChange={event => setAdvanced(event.target.checked)}/>高级 JSON 编辑</label>
        {!advanced && parsed && <ApplicationTemplateEditor key={template || (source ? exact(source) : 'draft')} definition={parsed} materials={materials} disabled={locked || !ready} onChange={next => { setDraft(JSON.stringify(next, null, 2)); setDraftError(''); }}/>}
        {!advanced && !parsed && <p className="list-empty">选择已发布应用作为起点，或开启高级 JSON 编辑。</p>}
        {advanced && <><label htmlFor="application-definition-json">应用定义 JSON</label><textarea id="application-definition-json" className="code-input" rows={14} maxLength={131072} value={draft} disabled={locked || !ready} onChange={event => { setDraft(event.target.value); setTemplate(''); setDraftError(''); }} required/><p className="quiet">完整字段保留。服务端核对材料、能力、连接与预算；版本与哈希由服务端生成。</p></>}
        {draftError && <div role="alert" className="error-message">{draftError}</div>}
        {pendingSave ? <div className="state-note"><p>保存结果尚未核对，原定义与请求标识已锁定。重试只核对同一次保存。刷新页面后请先检查应用版本列表，避免另建草稿。</p><button type="submit" className="primary" disabled={!!busy || !ready}>核对并重试原保存</button></div> : <button className="primary" disabled={locked || !ready || !draft.trim() || (!advanced && (!inspection.guided || inspection.errors.length > 0))}>{busy === 'draft-application' ? '等待草稿确认…' : source ? '保存新的应用版本' : '保存应用草稿'}</button>}
      </form>
    </section>
    <div className="section-heading"><h2>共享应用与我的草稿</h2></div>{isAdmin && <label className="retire-reason">归档或撤回原因<textarea aria-label="应用归档撤回原因" rows={2} value={reason} maxLength={1000} disabled={locked} onChange={event => setReason(event.target.value)} placeholder="填写具体原因，再选择对应版本的操作。"/></label>}
    {versions.map(item => <article className="material-row review-row" key={exact(item.application)}><div className="material-info"><h2>{item.application.name} · v{item.application.version}</h2><p>{labels[item.governance.state]} · 作者 {item.governance.author_id}{item.governance.bootstrap ? ' · 演示启动定义' : ''}</p>{item.governance.reason && <p>状态原因：{item.governance.reason}</p>}<ApplicationEvidence application={item.application} materials={materials}/></div><div className="material-actions"><button className="secondary" disabled={locked || !ready} onClick={() => load(item.application, true)}>载入并修订</button>{item.governance.state === 'draft' && item.governance.author_id === user.id && <button className="primary" disabled={locked || !ready} onClick={() => void publish(item.application)}>发布此版本</button>}{isAdmin && item.governance.state === 'published' && <button className="secondary danger" disabled={locked || !ready || !reason.trim()} onClick={() => void retire(item, 'withdraw')}>撤回此版本</button>}{isAdmin && item.governance.state !== 'archived' && <button className="secondary danger" disabled={locked || !ready || !reason.trim()} onClick={() => void retire(item, 'archive')}>归档此版本</button>}</div></article>)}{ready && !versions.length && <p className="list-empty">暂无可见的应用版本。</p>}
    <details className="technical-detail"><summary>历史发布审查（只读）</summary><p>原申请和决定保留，不会自动发布任何版本。</p><button className="secondary" disabled={locked || !ready} onClick={() => void readHistory()}>读取历史记录</button>{reviews.map(review => <article className="material-row review-row" key={review.id}><div className="material-info"><h2>{review.application.name} · v{review.application.version}</h2><p>{labels[review.decision]} · 作者 {review.authorId} · 当前版本 {labels[review.state]}</p><ApplicationEvidence application={review.application} materials={materials}/><details className="technical-detail"><summary>历史凭据</summary><span>审查 {review.id}</span><span>审查人 {review.reviewerId ?? '无历史决定'}</span><span>准确应用 {exact(review.application)}</span></details></div></article>)}{historyLoaded && !reviews.length && <p className="list-empty">暂无可见的历史发布审查。</p>}</details>

  </section>;
}
