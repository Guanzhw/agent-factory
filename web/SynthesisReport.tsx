interface Claim { text: string; sourceIds: string[]; quotes: { sourceId: string; text: string }[] }
interface Report { schema: 1; claims: Claim[]; limitations: string[] }
interface ReadyEvidence {
  schema: 1; status: 'ready'; evidenceKind: 'controlled_model_synthesis'; snapshotRef: { id: string; fingerprint: string };
  snapshotSha256: string; sourceEvidenceKind: 'controlled_literature_fixture' | 'public_literature_excerpt'; sourceCurrent: boolean | null;
  report: Report; citationStructureVerified: true; semanticReview: 'required'; scientificConclusionVerified: false;
  artifactIds: { json: string; markdown: string };
}
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown, max: number): v is string => typeof v === 'string' && !!v.trim() && [...v].length <= max;
const id = (v: unknown): v is string => typeof v === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(v);
const hash = (v: unknown) => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const exact = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
export function synthesisReportState(value: unknown): { kind: 'missing' | 'invalid' | 'pending' } | { kind: 'ready'; evidence: ReadyEvidence } {
  if (value === undefined || value === null) return { kind: 'missing' };
  if (!record(value) || !exact(value, ['schema', 'status', 'evidenceKind', 'snapshotRef', 'snapshotSha256', 'sourceEvidenceKind', 'sourceCurrent', 'report', 'citationStructureVerified', 'semanticReview', 'scientificConclusionVerified', 'artifactIds'])
      || value.schema !== 1 || value.evidenceKind !== 'controlled_model_synthesis' || value.semanticReview !== 'required' || value.scientificConclusionVerified !== false) return { kind: 'invalid' };
  if (value.status === 'pending' || value.status === 'invalid') {
    if (['snapshotRef', 'snapshotSha256', 'sourceEvidenceKind', 'sourceCurrent', 'report', 'artifactIds'].some(k => value[k] !== null) || value.citationStructureVerified !== false) return { kind: 'invalid' };
    return { kind: value.status };
  }
  if (value.status !== 'ready' || value.citationStructureVerified !== true || !record(value.snapshotRef) || !exact(value.snapshotRef, ['id', 'fingerprint'])
      || !id(value.snapshotRef.id) || !hash(value.snapshotRef.fingerprint) || !hash(value.snapshotSha256)
      || !['controlled_literature_fixture', 'public_literature_excerpt'].includes(String(value.sourceEvidenceKind))
      || !(value.sourceCurrent === null || typeof value.sourceCurrent === 'boolean') || !record(value.artifactIds) || !exact(value.artifactIds, ['json', 'markdown'])
      || !id(value.artifactIds.json) || !id(value.artifactIds.markdown) || value.artifactIds.json === value.artifactIds.markdown
      || !record(value.report) || !exact(value.report, ['schema', 'claims', 'limitations']) || value.report.schema !== 1
      || !Array.isArray(value.report.claims) || value.report.claims.length < 1 || value.report.claims.length > 3
      || !Array.isArray(value.report.limitations) || value.report.limitations.length < 1 || value.report.limitations.length > 5
      || !value.report.limitations.every(v => text(v, 400))) return { kind: 'invalid' };
  const quoted = new Map<string, { chars: number; words: number }>();
  for (const claim of value.report.claims) {
    if (!record(claim) || !exact(claim, ['text', 'sourceIds', 'quotes']) || !text(claim.text, 600) || !Array.isArray(claim.sourceIds)
        || claim.sourceIds.length < 1 || claim.sourceIds.length > 3 || !claim.sourceIds.every(v => text(v, 320)) || new Set(claim.sourceIds).size !== claim.sourceIds.length
        || !Array.isArray(claim.quotes) || claim.quotes.length > 3) return { kind: 'invalid' };
    for (const quote of claim.quotes) {
      if (!record(quote) || !exact(quote, ['sourceId', 'text']) || !text(quote.sourceId, 320) || !claim.sourceIds.includes(quote.sourceId) || !text(quote.text, 160)) return { kind: 'invalid' };
      const total = quoted.get(quote.sourceId) ?? { chars: 0, words: 0 }; total.chars += [...quote.text].length; total.words += quote.text.trim().split(/\s+/u).length;
      if (total.chars > 160 || total.words > 20) return { kind: 'invalid' }; quoted.set(quote.sourceId, total);
    }
  }
  return { kind: 'ready', evidence: value as unknown as ReadyEvidence };
}
export function SynthesisReport({ evidence }: { evidence?: unknown }) {
  const state = synthesisReportState(evidence);
  if (state.kind === 'missing') return null;
  if (state.kind !== 'ready') return <section aria-label="来源综合报告"><h3>来源综合报告</h3><p role={state.kind === 'invalid' ? 'alert' : 'status'}>{state.kind === 'invalid' ? '综合报告证据无法核对，不宣称引用结构或科研结论已验证。' : '综合报告尚待生成和核对。'}</p></section>;
  const value = state.evidence;
  return <section aria-label="来源综合报告" style={{ minWidth: 0, overflowWrap: 'anywhere' }}><h3>来源综合报告</h3>
    <p className="policy-note">受控模型输出，仅验证工作流。服务端已核对引用结构；这不等于科研结论验证，仍需领域人员进行语义审查。</p>
    <p>{value.sourceEvidenceKind === 'public_literature_excerpt' ? '输入来自公开文献的实际记录，覆盖范围以来源快照为准。' : '输入来源为受控测试样本。'} 未据此宣称使用了真实科学模型或取得全文。</p>
    {value.sourceCurrent !== true && <p className="policy-note">{value.sourceCurrent === false ? '原来源当前已变化或不可用；以下保留历史报告，不授权重新执行。' : '原来源当前状态尚未确认；历史报告不授权重新执行。'}</p>}
    <ol>{value.report.claims.map((claim, index) => <li key={index}><p>{claim.text}</p><p className="quiet">引用来源：{claim.sourceIds.join('、')}</p>{claim.quotes.map((quote, i) => <blockquote key={i}>{quote.text}<cite>来源 {quote.sourceId}</cite></blockquote>)}</li>)}</ol>
    <h4>限制与待审查事项</h4><ul>{value.report.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul>
    <p className="quiet">报告下载请使用本任务下方的产物列表；下载与校验沿用原任务权限。</p>
    <details className="technical-detail"><summary>综合报告绑定依据</summary><span>快照 {value.snapshotRef.id}</span><span>快照指纹 {value.snapshotRef.fingerprint}</span><span>来源上下文 {value.snapshotSha256}</span><span>JSON 产物 {value.artifactIds.json}</span><span>Markdown 产物 {value.artifactIds.markdown}</span></details>
  </section>;
}
