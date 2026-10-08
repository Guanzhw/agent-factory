import { useEffect, useRef, useState } from 'react';
import { ApiError } from './api.js';
import { useCommandKeys } from './commandKeys.js';
import { LiteratureEvidencePanel } from './LiteratureEvidence.js';
import { pendingSynthesisRequest, synthesisPage, synthesisPointerKey, synthesisPreview, synthesisSnapshot, SynthesisJourneyGuard, saveSynthesisOnce,
  type SynthesisCreate, type SynthesisJourneyApi, type SynthesisPage, type SynthesisPreview, type SynthesisSnapshot } from './synthesisJourneyState.js';
export interface SynthesisJourneyProps { ownerId: string; sourceTaskId: string; api: SynthesisJourneyApi; onSnapshot: (snapshot: SynthesisSnapshot) => void; disabled?: boolean }
export function SynthesisJourney({ ownerId, sourceTaskId, api, onSnapshot, disabled = false }: SynthesisJourneyProps) {
  const guard = useRef(new SynthesisJourneyGuard()); const epoch = guard.current.enter(ownerId, sourceTaskId);
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const transport = useRef(api); transport.current = api;
  const [loaded, setLoaded] = useState<{ epoch: number; preview?: SynthesisPreview; page?: SynthesisPage }>();
  const [selected, setSelected] = useState<string[]>([]); const [question, setQuestion] = useState('');
  const [chosen, setChosen] = useState<{ epoch: number; snapshot: SynthesisSnapshot }>();
  const [pending, setPending] = useState<{ epoch: number; requestId: string }>();
  const input = useRef<{ epoch: number; value: SynthesisCreate } | undefined>(undefined);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(true); const [refresh, setRefresh] = useState(0); const [after, setAfter] = useState<string>();
  const keys = useCommandKeys(ownerId); const pointerKey = synthesisPointerKey(ownerId, sourceTaskId);
  const preview = loaded?.epoch === epoch ? loaded.preview : undefined; const page = loaded?.epoch === epoch ? loaded.page : undefined;
  const snapshot = chosen?.epoch === epoch ? chosen.snapshot : undefined; const uncertain = pending?.epoch === epoch;
  function remember(requestId?: string) {
    if (!mounted.current || !guard.current.current(epoch)) return;
    setPending(requestId ? { epoch, requestId } : undefined);
    try { if (requestId) window.localStorage.setItem(pointerKey, requestId); else window.localStorage.removeItem(pointerKey); } catch { /* Keep this page locked if storage is unavailable. */ }
  }
  useEffect(() => {
    setSelected([]); setQuestion(''); setChosen(undefined); setLoaded(undefined); setAfter(undefined); input.current = undefined;
    let requestId: string | undefined; try { requestId = pendingSynthesisRequest(window.localStorage.getItem(pointerKey)); } catch { /* No private input is stored. */ }
    setPending(requestId ? { epoch, requestId } : undefined);
  }, [epoch, pointerKey]);
  useEffect(() => {
    const controller = new AbortController(); setBusy(true); setError('');
    const task = async () => {
      const results = await Promise.allSettled([transport.current.preview(sourceTaskId, controller.signal), transport.current.list(sourceTaskId, after, controller.signal)]);
      if (controller.signal.aborted || !mounted.current || !guard.current.current(epoch)) return;
      let preview: SynthesisPreview | undefined; let page: SynthesisPage | undefined; const failures: string[] = [];
      try { if (results[0].status === 'rejected') throw results[0].reason; preview = synthesisPreview(results[0].value, sourceTaskId, ownerId); } catch { failures.push('当前来源不可用或已变化；历史快照仍可只读查看。'); }
      try { if (results[1].status === 'rejected') throw results[1].reason; page = synthesisPage(results[1].value, ownerId, sourceTaskId); } catch { failures.push('快照历史读取失败，请重新核对。'); }
      setLoaded({ epoch, preview, page }); setError(failures.join(' ')); setBusy(false);
      let original: string | undefined; try { original = pendingSynthesisRequest(window.localStorage.getItem(pointerKey)); } catch { /* memory state is retained */ }
      if (original && page) {
        const found = page.items.find(item => item.requestId === original);
        if (found) { setChosen({ epoch, snapshot: found }); setPending(undefined); input.current = undefined; try { window.localStorage.removeItem(pointerKey); } catch { /* Read-only recovery is complete. */ } }
      }
    };
    void task(); return () => controller.abort();
  }, [epoch, sourceTaskId, ownerId, pointerKey, after, refresh]);
  async function save() {
    if (disabled || busy || !preview || !question.trim() || [...question.trim()].length > 1000 || !selected.length || selected.some(id => !preview.projection.sources.some(source => source.sourceId === id)) || uncertain && input.current?.epoch !== epoch || !guard.current.claim(epoch)) return;
    setBusy(true); setError(''); const client = transport.current;
    try {
      const payload = input.current?.epoch === epoch ? input.current.value : { sourceTaskId, sourceIds: [...selected], question: question.trim(), expectedFingerprint: preview.fingerprint, requestId: '' };
      if (!payload.requestId) { const key = await keys('synthesis-source-snapshot', payload); payload.requestId = key.requestId; }
      if (!mounted.current || !guard.current.current(epoch)) return;
      input.current = { epoch, value: payload }; remember(payload.requestId);
      const result = await saveSynthesisOnce(client, ownerId, payload);
      if (!mounted.current || !guard.current.current(epoch)) return;
      setChosen({ epoch, snapshot: result }); remember(); input.current = undefined; setAfter(undefined); setRefresh(n => n + 1);
    } catch (cause) {
      if (!mounted.current || !guard.current.current(epoch)) return;
      if (cause instanceof ApiError && cause.status === 422) { remember(); input.current = undefined; setError('问题或所选来源不符合综合契约，请调整后重新确认。来源摘录不会由浏览器自动裁剪。'); }
      else { setError('快照请求尚未确认；保留原请求，只读刷新历史核对。请勿另建请求绕过未知结果。'); setRefresh(n => n + 1); }
    } finally { guard.current.release(epoch); if (mounted.current && guard.current.current(epoch)) setBusy(false); }
  }
  async function choose(id: string) {
    if (disabled || busy || !guard.current.claim(epoch)) return;
    setBusy(true); setError('');
    try { const value = synthesisSnapshot(await transport.current.inspect(id), ownerId, sourceTaskId, id); if (mounted.current && guard.current.current(epoch)) { setChosen({ epoch, snapshot: value }); if (value.requestId === pending?.requestId) { remember(); input.current = undefined; } } }
    catch { if (mounted.current && guard.current.current(epoch)) setError('历史快照读取失败，未改变当前方案。'); }
    finally { guard.current.release(epoch); if (mounted.current && guard.current.current(epoch)) setBusy(false); }
  }
  async function prepare() {
    if (disabled || busy || uncertain || !snapshot || !guard.current.claim(epoch)) return;
    setBusy(true); setError('');
    try {
      const current = synthesisSnapshot(await transport.current.current(snapshot.id), ownerId, sourceTaskId, snapshot.id);
      if (current.fingerprint !== snapshot.fingerprint || current.contextFingerprint !== snapshot.contextFingerprint) throw new Error('changed');
      if (mounted.current && guard.current.current(epoch)) onSnapshot(current);
    } catch { if (mounted.current && guard.current.current(epoch)) setError('原来源当前不可用、已变化或权限不足。保留历史快照，不能据此准备新执行。'); }
    finally { guard.current.release(epoch); if (mounted.current && guard.current.current(epoch)) setBusy(false); }
  }
  const locked = disabled || busy || uncertain || !preview;
  return <section className="synthesis-journey" aria-label="来源综合工作流" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <h3>从已记录来源准备综合任务</h3><p className="state-note">当前仅支持受控模型综合，用于验证工作流，不是已验证的科研结论。公开来源不代表使用了真实科研模型；引用结构核对与领域审查分别进行。</p>
    <button type="button" className="secondary" disabled={disabled || busy} onClick={() => { setAfter(undefined); setRefresh(n => n + 1); }}>重新核对来源与快照</button>
    {busy && <p role="status">正在核对记录…</p>}{error && <p role="alert" className="error-message">{error}</p>}
    {uncertain && <p className="policy-note" role="status">原快照请求未确认，已锁定输入。刷新只读取历史，不会重新提交；重新进入页面后若缺少原输入，只能继续核对原记录。请求 {pending.requestId}</p>}
    {preview && <><LiteratureEvidencePanel detail={{ job: { id: sourceTaskId }, literatureEvidence: preview.projection }}/>
      <fieldset disabled={locked}><legend>选择本次综合依据</legend>{preview.projection.sources.map(source => <label key={source.sourceId}><input type="checkbox" aria-label={`选择来源 ${source.sourceId}`} checked={selected.includes(source.sourceId)} onChange={event => setSelected(values => event.target.checked ? [...values, source.sourceId] : values.filter(id => id !== source.sourceId))}/>{source.title || source.sourceId}</label>)}
      <label>综合问题<textarea aria-label="综合问题" rows={3} value={question} onChange={event => setQuestion(event.target.value)} maxLength={2000}/></label><small className="quiet">最多 1000 个 Unicode 字符。保存后问题与来源固定；修改需另建快照，不会改变旧记录。</small></fieldset>
      <button type="button" className="primary" disabled={disabled || busy || !selected.length || selected.some(id => !preview.projection.sources.some(source => source.sourceId === id)) || !question.trim() || [...question.trim()].length > 1000 || uncertain && input.current?.epoch !== epoch} onClick={() => void save()}>{uncertain ? '使用原请求核对并重试' : '确认来源并保存快照'}</button></>}
    <h4>此来源任务的快照历史</h4><p className="quiet">每页最多 20 条，不代表完整实时清单；查看不会创建方案或启动任务。</p>
    {page?.items.map(item => <p key={item.id}><button type="button" className="text-button" disabled={disabled || busy} onClick={() => void choose(item.id)}>查看快照：{item.question}</button></p>)}
    {page?.items.length === 0 && <p>当前页没有已保存快照。</p>}{page?.nextCursor && <button type="button" className="secondary" disabled={disabled || busy} onClick={() => setAfter(page.nextCursor!)}>读取下一页快照</button>}
    {snapshot && <section aria-label="来源快照"><h4>已保存的不可变来源快照</h4><p>{snapshot.question}</p><LiteratureEvidencePanel detail={{ job: { id: sourceTaskId }, literatureEvidence: snapshot.projection }}/><p>选择 {snapshot.sourceIds.length} 条来源；{snapshot.projection.evidenceKind === 'controlled_literature_fixture' ? '来源也是受控样本。' : '公开来源记录，覆盖范围以实际取得的摘要或摘录为准。'}</p><p className="quiet">下一步选择已批准的综合应用与自己的模型连接，再生成提案、审查方案和创建原生任务。本按钮只准备装配输入。</p>
      <button type="button" className="primary" disabled={disabled || busy || uncertain} onClick={() => void prepare()}>用此快照准备合成方案</button>
      <details className="technical-detail"><summary>快照与原来源凭据</summary><span>快照 {snapshot.id}</span><span>快照指纹 {snapshot.fingerprint}</span><span>来源上下文 {snapshot.contextFingerprint}</span><span>原来源 {snapshot.sourceFingerprint}</span>{snapshot.artifacts.map(a => <span key={a.id}>产物 {a.id} · SHA-256 {a.sha256}</span>)}</details></section>}
  </section>;
}
