import { useEffect, useRef, useState } from 'react';
import { api } from './api.js';
import { kindNames, materialKey } from './models.js';
import type { FactoryMaterial, MaterialDraft, MaterialGovernancePolicy, MaterialReview, User } from './models.js';

type Act = (name: string, work: () => Promise<void>) => Promise<void>;
type Provenance = { kind: 'original' | 'upstream'; source?: string | null; revision?: string | null; notice: string };
type Draft = MaterialDraft & { license: string; provenance: Provenance; compatibility: string[]; inputSchema: Record<string, unknown>; outputSchema: Record<string, unknown> };
type StatusIntent = { material: FactoryMaterial; action: 'archive' | 'withdraw'; reason: string };
const licenses = ['MIT', 'Apache-2.0', 'BSD-2-Clause', 'BSD-3-Clause', 'CC0-1.0', 'CC-BY-4.0'];
const tools: Record<string, string> = { literature_search: 'research:read', ask_scope: 'question:ask', checksum: 'checksum:read', run_experiment: 'experiment:synthetic' };
const stateNames: Record<string, string> = { draft: '草稿', published: '已发布', withdrawn: '已撤回', archived: '已归档' };
const decisionNames: Record<string, string> = { pending: '等待审核', approved: '已同意', denied: '已拒绝' };
const describe = (error: unknown) => error instanceof Error ? error.message : '素材治理状态无法确认，请刷新后重试。';
const freshDraft = (): Draft => ({ name: '', kind: 'skill', description: '', content: '', dependencies: [], permissions: [], license: 'MIT', provenance: { kind: 'original', notice: 'Original manager-authored material.' }, compatibility: ['agno:3.1.0'], inputSchema: {}, outputSchema: {} });
const stateOf = (material: FactoryMaterial) => material.governance?.state ?? (material.archived ? 'archived' : material.published ? 'published' : 'draft');
const active = (material: FactoryMaterial) => stateOf(material) === 'published' && material.published;

function isReview(value: unknown): value is MaterialReview {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const review = value as Record<string, unknown>;
  const body = review.material;
  if (!body || typeof body !== 'object' || Array.isArray(body)) return false;
  const material = body as Record<string, unknown>;
  const strings = (items: unknown) => Array.isArray(items) && items.every(item => typeof item === 'string');
  const hash = (item: unknown) => typeof item === 'string' && /^[a-f0-9]{64}$/.test(item);
  return typeof review.id === 'string' && typeof review.authorId === 'string' && typeof review.requestedBy === 'string' &&
    typeof review.materialId === 'string' && Number.isInteger(review.version) && Number(review.version) > 0 &&
    typeof review.createdAt === 'string' && typeof review.policyRevision === 'string' && hash(review.sha256) && hash(review.immutableDigest) &&
    typeof review.currentPolicy === 'boolean' && typeof review.demoCompatibility === 'boolean' && review.taskApprovalSeparate === true &&
    ['pending', 'approved', 'denied'].includes(String(review.decision)) && ['draft', 'published', 'withdrawn', 'archived'].includes(String(review.state)) &&
    typeof material.id === 'string' && Number.isInteger(material.version) && typeof material.name === 'string' &&
    typeof material.kind === 'string' && Object.hasOwn(kindNames, material.kind) && typeof material.content === 'string' &&
    typeof material.license === 'string' && hash(material.sha256) && strings(material.permissions) && strings(material.compatibility) &&
    Array.isArray(material.dependencies) && material.dependencies.every(item => !!item && typeof item === 'object' && typeof item.id === 'string' && Number.isInteger(item.version) && hash(item.sha256)) &&
    !!material.inputSchema && typeof material.inputSchema === 'object' && !Array.isArray(material.inputSchema) &&
    !!material.outputSchema && typeof material.outputSchema === 'object' && !Array.isArray(material.outputSchema);
}

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, canonical(item)]));
  return value;
}

// Persist only command hashes and opaque IDs, never material content or secrets.
function useCommands(userId: string) {
  const memory = useRef(new Map<string, string>());
  async function key(operation: string, payload: unknown) {
    const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(canonical(payload))));
    const fingerprint = Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('');
    const storageKey = `factory-material-command-v1:${encodeURIComponent(userId)}:${operation}:${fingerprint}`;
    let saved = memory.current.get(storageKey);
    if (!saved) {
      try { saved = window.sessionStorage.getItem(storageKey) ?? undefined; } catch { /* Current-page retries still retain their key. */ }
      if (!saved || !/^[0-9a-f-]{36}$/.test(saved)) saved = crypto.randomUUID();
      memory.current.set(storageKey, saved);
      try { window.sessionStorage.setItem(storageKey, saved); } catch { /* Storage may be disabled by the browser. */ }
    }
    return { requestId: saved, acknowledged() { memory.current.delete(storageKey); try { window.sessionStorage.removeItem(storageKey); } catch { /* No content was stored. */ } } };
  }
  return { key };
}

function objectSchema(text: string, label: string): Record<string, unknown> {
  let value: unknown;
  try { value = JSON.parse(text); } catch { throw new Error(`${label}必须是有效 JSON 对象。`); }
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label}必须是 JSON 对象。`);
  return value as Record<string, unknown>;
}

function MaterialContent({ material }: { material: FactoryMaterial }) {
  const provenance = material.provenance;
  return <dl className="plan-details">
    <dt>完整内容{material.kind === 'tool' ? ' / 注册工具绑定' : ''}</dt><dd><pre>{material.content}</pre></dd>
    <dt>声明权限</dt><dd>{material.permissions.length ? material.permissions.join('、') : '未请求额外权限'}</dd>
    <dt>固定依赖版本</dt><dd>{material.dependencies.length ? <pre>{JSON.stringify(material.dependencies, null, 2)}</pre> : '无依赖'}</dd>
    <dt>许可证</dt><dd>{material.license || '未提供'}</dd>
    <dt>来源与许可声明</dt><dd>{provenance ? <><span>{provenance.kind === 'original' ? '作者原创' : '上游引用'}</span>{provenance.source && <span style={{ display: 'block', overflowWrap: 'anywhere' }}>来源：{provenance.source}</span>}{provenance.revision && <span style={{ display: 'block', overflowWrap: 'anywhere' }}>固定修订：{provenance.revision}</span>}<pre>{provenance.notice}</pre></> : material.origin || '未提供；需核对原始版本记录'}</dd>
    <dt>运行兼容性</dt><dd>{material.compatibility.join('、') || '未提供'}</dd>
    <dt>输入 / 输出结构</dt><dd><pre>{JSON.stringify({ inputSchema: material.inputSchema, outputSchema: material.outputSchema }, null, 2)}</pre></dd>
    <dt>精确内容摘要</dt><dd style={{ overflowWrap: 'anywhere' }}>{material.sha256}</dd>
  </dl>;
}

export function MaterialGovernancePanel({ user, materials, busy, act, onNotice }: { user: User; materials: FactoryMaterial[]; busy: string; act: Act; onNotice: (message: string) => void }) {
  const [filter, setFilter] = useState('all');
  const [policy, setPolicy] = useState<MaterialGovernancePolicy>();
  const [reviews, setReviews] = useState<MaterialReview[]>([]);
  const [allAuthors, setAllAuthors] = useState(false);
  const [authorityCurrent, setAuthorityCurrent] = useState(false);
  const [pollError, setPollError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft>(freshDraft);
  const [permissionText, setPermissionText] = useState('');
  const [inputSchema, setInputSchema] = useState('{}');
  const [outputSchema, setOutputSchema] = useState('{}');
  const [importing, setImporting] = useState(false);
  const [importText, setImportText] = useState('');
  const [selectedReview, setSelectedReview] = useState('');
  const [statusIntent, setStatusIntent] = useState<StatusIntent>();
  const commands = useCommands(user.id);
  const disabled = !!busy || !authorityCurrent;
  const visible = materials.filter(material => filter === 'all' || material.kind === filter);
  const dependencies = materials.filter(material => active(material) && material.id !== draft.id);
  const unavailable = draft.dependencies.filter(ref => !dependencies.some(material => materialKey(material) === materialKey(ref) && material.sha256 === ref.sha256));

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    setAuthorityCurrent(false);
    async function poll() {
      try {
        const currentUser = await api.session(controller.signal);
        if (currentUser.id !== user.id || currentUser.role !== 'manager') throw new Error('当前身份已改变或失去素材管理权限，请重新登录。');
        const [nextPolicy, nextReviews] = await Promise.all([api.materialPolicy(controller.signal), api.materialReviews(allAuthors, controller.signal)]);
        if (nextPolicy.review_mode !== 'separate-admin' && nextPolicy.review_mode !== 'demo-self-review') throw new Error('素材发布策略无法识别，请等待管理员核对。');
        if (typeof nextPolicy.revision !== 'string' || typeof nextPolicy.fingerprint !== 'string' || !/^[a-f0-9]{64}$/.test(nextPolicy.fingerprint) ||
          nextPolicy.taskApprovalSeparate !== true || nextPolicy.importExecutesCode !== false || nextPolicy.demoCompatibility !== (nextPolicy.review_mode === 'demo-self-review') ||
          !Array.isArray(nextReviews) || nextReviews.length > 100 || !nextReviews.every(isReview)) throw new Error('素材审核响应不完整，暂时无法确认写操作权限。');
        if (!controller.signal.aborted) { setPolicy(nextPolicy); setReviews(nextReviews); setPollError(''); setAuthorityCurrent(true); }
      } catch (error) {
        if (!controller.signal.aborted) { setPollError(describe(error)); setAuthorityCurrent(false); }
      }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 5000);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [user.id, allAuthors, refresh]);

  function edit(material?: FactoryMaterial) {
    const next: Draft = material ? {
      id: material.id, name: material.name, kind: material.kind, description: material.description, content: material.content,
      dependencies: material.dependencies, permissions: material.permissions, license: material.license || 'MIT',
      provenance: material.provenance ?? { kind: 'original', notice: 'Original manager-authored material.' },
      compatibility: material.compatibility, inputSchema: material.inputSchema, outputSchema: material.outputSchema,
    } : freshDraft();
    setDraft(next); setPermissionText(next.permissions.join('\n')); setInputSchema(JSON.stringify(next.inputSchema, null, 2));
    setOutputSchema(JSON.stringify(next.outputSchema, null, 2)); setEditing(true); setImporting(false);
  }
  function dependency(material: FactoryMaterial, checked: boolean) {
    setDraft(current => ({ ...current, dependencies: checked ? [...current.dependencies.filter(ref => materialKey(ref) !== materialKey(material)), { id: material.id, version: material.version, sha256: material.sha256 }] : current.dependencies.filter(ref => materialKey(ref) !== materialKey(material)) }));
  }
  function chooseKind(kind: Draft['kind']) {
    const tool = kind === 'tool' ? 'literature_search' : undefined;
    setDraft(current => ({ ...current, kind, content: tool ?? current.content, permissions: tool ? [tools[tool]] : [] }));
    setPermissionText(tool ? tools[tool] : '');
  }
  async function saveDraft() {
    await act('governance-draft', async () => {
      const definition: Record<string, unknown> = { ...draft, name: draft.name.trim(), description: draft.description.trim(),
        permissions: draft.kind === 'tool' ? [tools[draft.content]] : [...new Set(permissionText.split('\n').map(value => value.trim()).filter(Boolean))],
        inputSchema: objectSchema(inputSchema, '输入结构'), outputSchema: objectSchema(outputSchema, '输出结构') };
      const command = await commands.key('draft', definition);
      const saved = await api.governanceDraft(definition, command.requestId);
      command.acknowledged(); setEditing(false); setRefresh(value => value + 1);
      onNotice(`草稿已保存：${saved.name} v${saved.version}，还需单独申请发布。`);
    });
  }
  async function importDefinitions() {
    await act('governance-import', async () => {
      let value: unknown;
      try { value = JSON.parse(importText); } catch { throw new Error('导入内容必须是有效 JSON 数组。'); }
      if (!Array.isArray(value) || value.length < 1 || value.length > 30 || value.some(item => !item || typeof item !== 'object' || Array.isArray(item))) throw new Error('导入需要 1 至 30 个结构化定义对象。');
      const definitions = value as Record<string, unknown>[];
      if (definitions.some(item => typeof item.license !== 'string' || !item.provenance || typeof item.provenance !== 'object' || Array.isArray(item.provenance))) throw new Error('每个导入定义必须显式提供 license 和 provenance。');
      const command = await commands.key('import', definitions);
      const saved = await api.importMaterials(definitions, command.requestId);
      command.acknowledged(); setImportText(''); setImporting(false); setRefresh(number => number + 1);
      onNotice(`已登记 ${saved.materials.length} 个版本草稿；请分别申请发布。`);
    });
  }
  async function requestPublication(material: FactoryMaterial) {
    await act('request-material-publication', async () => {
      const previous = reviews.find(review => review.materialId === material.id && review.version === material.version);
      const operation = `publication:${materialKey(material)}:${policy?.revision}:${previous?.id ?? 'initial'}`;
      const command = await commands.key(operation, { materialId: material.id, version: material.version, sha256: material.sha256 });
      const saved = await api.requestMaterialPublication(material.id, material.version, command.requestId);
      setSelectedReview(saved.id); setRefresh(number => number + 1);
      onNotice(`已提交 ${material.name} v${material.version} 的精确版本发布申请。`);
    });
  }
  async function decide(review: MaterialReview, approved: boolean) {
    await act('decide-material-publication', async () => {
      const command = await commands.key(`decision:${review.id}`, { approved, sha256: review.sha256, policyRevision: review.policyRevision });
      await api.decideMaterialReview(review.id, approved, command.requestId);
      setRefresh(number => number + 1);
      onNotice(`${review.material.name} v${review.version} 的发布申请已${approved ? '同意' : '拒绝'}。`);
    });
  }
  async function changeStatus() {
    if (!statusIntent) return;
    const intent = statusIntent;
    await act(`material-${intent.action}`, async () => {
      const reason = intent.reason.trim();
      if (!reason) throw new Error('请填写撤回或归档原因。');
      const command = await commands.key(`${intent.action}:${materialKey(intent.material)}`, { sha256: intent.material.sha256, reason });
      if (intent.action === 'archive') await api.archiveMaterial(intent.material.id, intent.material.version, reason, command.requestId);
      else await api.withdrawMaterial(intent.material.id, intent.material.version, reason, command.requestId);
      setStatusIntent(undefined); setRefresh(number => number + 1);
      onNotice(`${intent.material.name} v${intent.material.version} 已${intent.action === 'archive' ? '归档' : '撤回'}；原始版本和历史证据仍保留。`);
    });
  }

  return <section className="materials-page">
    <div className="page-heading"><div><h1>构建材料管理</h1><p>维护固定版本的材料，先保存草稿，再申请独立发布审核。</p></div><div className="button-row"><button className="secondary" disabled={disabled} onClick={() => { setImporting(true); setEditing(false); }}>导入定义</button><button className="primary" disabled={disabled} onClick={() => edit()}>新建材料</button></div></div>
    <div className="state-note" role="status">{policy ? policy.demoCompatibility ? '当前明确启用了演示自审兼容模式。' : '当前要求由作者以外的管理员审核发布。' : '正在读取素材发布策略。'} 素材发布与任务执行审批分别记录。</div>
    {pollError && <div className="error-message" role="alert"><span>{pollError} 写操作暂时暂停。</span><button className="text-button" disabled={!!busy} onClick={() => setRefresh(value => value + 1)}>重新核对</button></div>}
    {editing && <section className="material-editor" aria-label="材料版本草稿"><div className="section-heading"><h2>{draft.id ? '编辑下一版本草稿' : '新建版本草稿'}</h2><button className="text-button" disabled={!!busy} onClick={() => setEditing(false)}>关闭编辑</button></div><form onSubmit={event => { event.preventDefault(); if (!disabled) void saveDraft(); }}>
      <div className="editor-grid"><label>名称<input value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} required maxLength={120} disabled={disabled}/></label><label>类型<select value={draft.kind} onChange={event => chooseKind(event.target.value as Draft['kind'])} disabled={disabled || !!draft.id}>{Object.entries(kindNames).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label></div>
      <label>用途说明<input value={draft.description} onChange={event => setDraft({ ...draft, description: event.target.value })} maxLength={2000} disabled={disabled}/></label>
      {draft.kind === 'tool' ? <label>注册工具<select value={draft.content} required disabled={disabled} onChange={event => { const content = event.target.value; setDraft({ ...draft, content, permissions: [tools[content]] }); setPermissionText(tools[content]); }}><option value="" disabled>选择已有工具</option>{Object.keys(tools).map(name => <option key={name} value={name}>{name}</option>)}</select></label> : <label>材料内容<textarea value={draft.content} onChange={event => setDraft({ ...draft, content: event.target.value })} rows={6} required maxLength={16000} disabled={disabled}/></label>}
      <label>声明权限（每行一项）<textarea value={permissionText} onChange={event => setPermissionText(event.target.value)} rows={2} disabled={disabled || draft.kind === 'tool'} placeholder="research:read"/></label><p className="quiet">可用权限：{Object.values(tools).join('、')}。连接凭据应通过受信连接提供。</p>
      <div className="editor-grid"><label>许可证<select value={draft.license} disabled={disabled} onChange={event => setDraft({ ...draft, license: event.target.value })}>{licenses.map(license => <option key={license}>{license}</option>)}</select></label><label>来源类型<select value={draft.provenance.kind} disabled={disabled} onChange={event => setDraft({ ...draft, provenance: { ...draft.provenance, kind: event.target.value as Provenance['kind'] } })}><option value="original">作者原创</option><option value="upstream">上游引用</option></select></label></div>
      {draft.provenance.kind === 'upstream' && <><label>上游来源（HTTPS）<input type="url" value={draft.provenance.source ?? ''} required maxLength={1000} disabled={disabled} onChange={event => setDraft({ ...draft, provenance: { ...draft.provenance, source: event.target.value } })}/></label><label>固定修订版本<input value={draft.provenance.revision ?? ''} required maxLength={200} disabled={disabled} onChange={event => setDraft({ ...draft, provenance: { ...draft.provenance, revision: event.target.value } })}/></label></>}
      <label>来源及版权声明<textarea value={draft.provenance.notice} required maxLength={4000} rows={3} disabled={disabled} onChange={event => setDraft({ ...draft, provenance: { ...draft.provenance, notice: event.target.value } })}/></label>
      <fieldset className="dependency-picker" disabled={disabled}><legend>依赖的已发布版本</legend>{dependencies.map(material => <label key={materialKey(material)}><input type="checkbox" checked={draft.dependencies.some(ref => materialKey(ref) === materialKey(material) && ref.sha256 === material.sha256)} onChange={event => dependency(material, event.target.checked)}/>{material.name} <small>v{material.version}</small></label>)}{!dependencies.length && <p className="quiet">暂无当前可用的已发布依赖。</p>}</fieldset>
      {!!unavailable.length && <div className="state-note">当前依赖中有 {unavailable.length} 个版本不可用，请核对后移除或重新选择。<button type="button" className="text-button" disabled={disabled} onClick={() => setDraft({ ...draft, dependencies: draft.dependencies.filter(ref => !unavailable.includes(ref)) })}>移除不可用依赖</button></div>}
      <details className="technical-detail"><summary>输入、输出与固定版本</summary><span>{draft.id ? `材料系列 ${draft.id}` : '保存时创建新的材料系列'} · 兼容性 {draft.compatibility.join('、')}</span><label>输入结构 JSON<textarea rows={3} value={inputSchema} maxLength={16000} disabled={disabled} onChange={event => setInputSchema(event.target.value)}/></label><label>输出结构 JSON<textarea rows={3} value={outputSchema} maxLength={16000} disabled={disabled} onChange={event => setOutputSchema(event.target.value)}/></label></details>
      <button className="primary" disabled={disabled}>保存版本草稿</button><p className="quiet">提交结果不明确时，保留内容并重试；相同内容会使用原请求标识核对。</p>
    </form></section>}
    {importing && <section className="material-editor" aria-label="导入结构化材料"><div className="section-heading"><h2>导入定义草稿</h2><button className="text-button" disabled={!!busy} onClick={() => setImporting(false)}>关闭导入</button></div><form onSubmit={event => { event.preventDefault(); if (!disabled) void importDefinitions(); }}><label>JSON 定义数组<textarea rows={12} value={importText} maxLength={262144} required disabled={disabled} onChange={event => setImportText(event.target.value)} placeholder={'[{"kind":"prompt","name":"研究提示词","content":"记录来源、方法与局限。","license":"MIT","provenance":{"kind":"original","notice":"Original manager-authored material."}}]'}/></label><p className="quiet">每次 1 至 30 个定义。须明确许可证和来源；上游引用须保留版权声明及固定修订。导入只保存定义，工具需绑定已注册工具。</p><button className="primary" disabled={disabled}>登记导入草稿</button></form></section>}
    <div className="catalog-tabs" role="group" aria-label="材料类型"><button aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>全部</button>{Object.entries(kindNames).map(([id, name]) => <button key={id} aria-pressed={filter === id} onClick={() => setFilter(id)}>{name}</button>)}</div>
    <div className="material-catalog">{visible.length ? visible.map(material => {
      const state = stateOf(material);
      const pending = reviews.some(review => review.materialId === material.id && review.version === material.version && review.decision === 'pending' && review.currentPolicy && review.state !== 'withdrawn' && review.state !== 'archived');
      return <article className="material-row" key={materialKey(material)}><div className="material-kind">{kindNames[material.kind]}</div><div className="material-info"><div className="material-title"><h3>{material.name}</h3><span className="version">v{material.version}</span><span className={`badge ${state === 'published' ? 'status-published' : 'status-draft'}`}>{stateNames[state] ?? '状态待核对'}</span></div><p>{material.description}</p><div className="material-meta"><span>作者 {material.governance?.authorId ?? '原始记录'}</span><span>许可证 {material.license}</span><span>依赖 {material.dependencies.length} 项</span></div>{material.governance?.reason && <p>状态原因：{material.governance.reason}</p>}<details className="technical-detail"><summary>查看完整版本内容</summary><MaterialContent material={material}/></details></div><div className="material-actions"><button className="secondary" disabled={disabled} onClick={() => edit(material)}>新版本</button>{state === 'draft' && <button className="primary" disabled={disabled || pending} onClick={() => void requestPublication(material)}>{pending ? '等待发布审核' : '申请发布此版本'}</button>}{state === 'published' && <button className="secondary danger" disabled={disabled} onClick={() => setStatusIntent({ material, action: 'withdraw', reason: '' })}>撤回此版本</button>}{state !== 'archived' && <button className="text-button" disabled={disabled} onClick={() => setStatusIntent({ material, action: 'archive', reason: '' })}>归档此版本</button>}</div></article>;
    }) : <p className="list-empty">此分类暂无可见材料。</p>}</div>
    {statusIntent && <section className="material-editor" aria-label="确认材料状态变更" style={{ marginTop: 24 }}><h2>{statusIntent.action === 'archive' ? '归档' : '撤回'} {statusIntent.material.name} v{statusIntent.material.version}</h2><p>此版本将无法用于后续执行。版本内容、摘要和历史证据继续保留。</p><form onSubmit={event => { event.preventDefault(); if (!disabled) void changeStatus(); }}><label>原因<textarea value={statusIntent.reason} rows={3} required maxLength={2000} disabled={disabled} onChange={event => setStatusIntent({ ...statusIntent, reason: event.target.value })}/></label><div className="button-row"><button className="secondary danger" disabled={disabled}>确认{statusIntent.action === 'archive' ? '归档' : '撤回'}此版本</button><button type="button" className="secondary" disabled={!!busy} onClick={() => setStatusIntent(undefined)}>取消</button></div><details className="technical-detail"><summary>查看固定版本摘要</summary><span>{materialKey(statusIntent.material)}</span><span>{statusIntent.material.sha256}</span></details></form></section>}
    <section aria-label="材料发布审核" style={{ marginTop: 30 }}><div className="section-heading"><h2>材料发布审核</h2><button className="secondary" disabled={!!busy} onClick={() => setRefresh(value => value + 1)}>刷新审核</button></div><label style={{ display: 'flex', alignItems: 'center', gap: 8 }}><input type="checkbox" checked={allAuthors} disabled={!!busy} onChange={event => { setAuthorityCurrent(false); setAllAuthors(event.target.checked); }}/>查看全部作者的申请（需当前管理员权限）</label><p className="quiet">先核对完整固定版本，再提交发布决定。发布审核不会代替任何任务审批。</p>{reviews.length ? reviews.map(review => {
      const consistent = review.material.id === review.materialId && review.material.version === review.version && review.material.sha256 === review.sha256;
      const compatible = policy?.demoCompatibility === true && review.demoCompatibility === true && policy.review_mode === 'demo-self-review';
      const self = review.authorId === user.id;
      const current = review.currentPolicy && review.policyRevision === policy?.revision;
      const actionable = review.decision === 'pending' && current && consistent && review.state !== 'withdrawn' && review.state !== 'archived';
      const inspect = selectedReview === review.id;
      return <article className="material-row review-row" key={review.id}><div className="material-info"><div className="material-title"><h3>{review.material.name}</h3><span className="version">v{review.version}</span><span className="badge">{decisionNames[review.decision]}</span></div><p>作者 {review.authorId} · 请求人 {review.requestedBy}{!current ? ' · 发布策略已改变' : ''}{review.state === 'withdrawn' || review.state === 'archived' ? ` · ${stateNames[review.state]}` : ''}</p>{self && !compatible && <p className="quiet">此版本由你创作，需要另一位当前管理员审核。</p>}{!consistent && <div className="error-message" role="alert">审核内容与精确版本摘要不一致，暂时无法提交决定。</div>}<button className="text-button" aria-expanded={inspect} onClick={() => setSelectedReview(inspect ? '' : review.id)}>{inspect ? '收起版本内容' : '查看并审核完整版本'}</button>{inspect && <div><MaterialContent material={review.material}/><details className="technical-detail"><summary>发布审核记录</summary><span>审核编号 {review.id}</span><span>策略版本 {review.policyRevision}</span><span>不可变记录摘要 {review.immutableDigest}</span><span>申请时间 {new Date(review.createdAt).toLocaleString('zh-CN')}</span><span>审核人 {review.reviewerId ?? '尚未审核'}</span>{review.decidedAt && <span>决定时间 {new Date(review.decidedAt).toLocaleString('zh-CN')}</span>}</details></div>}</div><div className="material-actions">{inspect && review.decision === 'pending' && <><button className="primary" disabled={disabled || !actionable || self && !compatible} onClick={() => void decide(review, true)}>同意发布此版本</button><button className="secondary danger" disabled={disabled || !actionable || self && !compatible} onClick={() => void decide(review, false)}>拒绝发布</button></>}</div></article>;
    }) : <p className="list-empty">暂无可见的材料发布申请。</p>}</section>
  </section>;
}
