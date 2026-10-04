import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { ComparisonPanel, ComparisonReport } from '../web/ComparisonPanel.js';
import { comparisonCatalog, comparisonEvidence, comparisonInput } from '../web/comparisonState.js';
const a = 'a'.repeat(64), b = 'b'.repeat(64), c = 'c'.repeat(64);
function input() { return { schema: 1, evidenceKind: 'synthetic_comparison_input', choice: 'linear-v1', dataset: { path: 'data.json', sha256: a, origin: 'synthetic', license: 'MIT', sampleSetSha256: b, sampleCount: 7 }, evaluator: { path: 'evaluate.py', sha256: b, protocolRevision: 'v1' }, baselineFiles: { 'data.json': a, 'evaluate.py': b, 'predict.py': a }, candidateFiles: { 'data.json': a, 'evaluate.py': b, 'predict.py': c }, allowedChanges: ['predict.py'], metric: { id: 'mse', unit: 'squared-error', direction: 'minimize', minimumImprovement: 0 }, seed: 0, resourceLimits: { cpu: 1, memoryMb: 128, wallSeconds: 5, outputBytes: 16384 } }; }
function observation(value: number) { return { schema: 1, contractSha256: a, variantSha256: b, datasetSha256: a, evaluatorSha256: b, sampleSetSha256: b, sampleCount: 7, seed: 0, metricId: 'mse', unit: 'squared-error', status: 'completed', value, resultSha256: a }; }
function evidence() { return { schema: 1, evidenceKind: 'controlled_comparison', ownerId: 'alice', taskId: 'task-1', planId: 'plan-1', nativeRunId: 'run-1', choice: 'linear-v1', status: 'ready', executionVerified: true, scientificConclusionVerified: false, contractSha256: a, candidateSha256: b, input: input(), baseline: observation(5), candidate: observation(2), assessment: { schema: 1, evidenceKind: 'offline_comparison_assessment', contractSha256: a, candidateSha256: b, status: 'improved', improvement: 3, metric: input().metric, reasons: [] as string[], executionVerified: false, scientificConclusionVerified: false }, artifactIds: { raw: 'raw-1', report: 'report-1' }, artifactHashes: { raw: a, report: b }, process: { leaseId: 'lease-1', providerJobId: 'job-1', executionStatus: 'COMPLETED', exitCode: 0, allStopped: true, capacityHeld: false } }; }
const scope = { ownerId: 'alice', taskId: 'task-1', planId: 'plan-1', artifacts: [{ id: 'raw-1', sha256: a, size: 24 }, { id: 'report-1', sha256: b, size: 48 }] };
function catalog() { return { schema: 1, ownerId: 'alice', evidenceKind: 'controlled_comparison', scientificConclusionVerified: false, items: [{ applicationRef: { id: 'comparison-app', version: 1, sha256: a }, mode: 'linear-v1', name: '固定比较', goal: '比较基线与候选', input: input() }] }; }
const render = (value: unknown) => renderToStaticMarkup(createElement(ComparisonReport, { ...scope, evidence: value }));
describe('controlled baseline/candidate comparison', () => {
  it('accepts fixed synthetic inputs without widening change scope or replacing evaluator/data', () => {
    expect(comparisonInput(input()).choice).toBe('linear-v1');
    for (const patch of [{ candidateFiles: { ...input().candidateFiles, 'data.json': c } }, { allowedChanges: ['evaluate.py'] }, { baselineFiles: { ...input().baselineFiles, '../escape': a } }, { dataset: { ...input().dataset, origin: 'private' } }, { resourceLimits: { ...input().resourceLimits, cpu: 65 } }]) expect(() => comparisonInput({ ...input(), ...patch })).toThrow();
  });
  it('requires owner-scoped governed catalog pins and does not create execution on render', () => {
    expect(comparisonCatalog(catalog(), 'alice')).toHaveLength(1);
    expect(() => comparisonCatalog(catalog(), 'bob')).toThrow();
    expect(() => comparisonCatalog({ ...catalog(), items: [{ ...catalog().items[0], mode: 'offset-v1' }] }, 'alice')).toThrow();
    expect(() => comparisonCatalog({ ...catalog(), items: [...catalog().items, ...catalog().items] }, 'alice')).toThrow();
    const onPrepare = vi.fn(); const api = { catalog: vi.fn() };
    const html = renderToStaticMarkup(createElement(ComparisonPanel, { ownerId: 'alice', api, onPrepare }));
    expect(html).toContain('合成开发数据'); expect(html).not.toContain('用此比较准备方案'); expect(onPrepare).not.toHaveBeenCalled(); expect(api.catalog).not.toHaveBeenCalled();
  });
  it('ranks only complete matching observations with verified stopped/released execution and matching artifacts', () => {
    expect(comparisonEvidence(evidence(), scope)).toMatchObject({ kind: 'verified', ranked: true });
    const html = render(evidence()); expect(html).toContain('候选指标改善'); expect(html).toContain('基线记录值'); expect(html).toContain('不代表统计显著性'); expect(html).not.toContain('href=');
  });
  it('rejects cross-owner/task/plan/native and altered artifact provenance', () => {
    for (const patch of [{ ownerId: 'bob' }, { taskId: 'other' }, { planId: 'other' }, { nativeRunId: null }, { executionVerified: false }, { scientificConclusionVerified: true }, { artifactHashes: { raw: c, report: b } }, { artifactIds: { raw: 'absent', report: 'report-1' } }]) expect(comparisonEvidence({ ...evidence(), ...patch }, scope).kind).toBe('invalid');
    expect(comparisonEvidence(evidence(), { ...scope, artifacts: [] }).kind).toBe('invalid');
  });
  it('binds both observations to the exact paired raw output artifact bytes', () => {
    for (const side of ['baseline', 'candidate'] as const) {
      const value = evidence(); value[side].resultSha256 = c;
      expect(comparisonEvidence(value, scope).kind).toBe('invalid');
    }
  });
  it('rejects mismatched sample sets, evaluator, metric, threshold and invented improvement', () => {
    for (const patch of [{ sampleSetSha256: c }, { evaluatorSha256: c }, { sampleCount: 6 }, { metricId: 'accuracy' }, { seed: 7 }, { value: Infinity }]) expect(comparisonEvidence({ ...evidence(), candidate: { ...observation(2), ...patch } }, scope).kind).toBe('invalid');
    for (const patch of [{ improvement: 100 }, { status: 'regressed' }, { executionVerified: true }, { reasons: ['invented'] }]) expect(comparisonEvidence({ ...evidence(), assessment: { ...evidence().assessment, ...patch } }, scope).kind).toBe('invalid');
  });
  it('displays verified workflow failure evidence without ranking a failed candidate', () => {
    const value = { ...evidence(), candidate: { ...observation(2), status: 'failed', value: null }, assessment: { ...evidence().assessment, status: 'inconclusive', improvement: null, reasons: ['CANDIDATE_FAILED'] } };
    expect(comparisonEvidence(value, scope)).toMatchObject({ kind: 'verified', ranked: false });
    const html = render(value); expect(html).toContain('工作流产物已核对不代表双方评估成功'); expect(html).not.toContain('基线记录值'); expect(html).not.toContain('候选指标改善');
    expect(comparisonEvidence({ ...value, assessment: evidence().assessment }, scope).kind).toBe('invalid');
  });
  it('keeps failed/cancelled/unknown outer outcomes unranked and rejects an assessment attached to them', () => {
    for (const status of ['pending', 'failed', 'cancelled', 'unknown']) {
      const value = { ...evidence(), status, executionVerified: false, baseline: null, candidate: null, assessment: null, artifactIds: null, artifactHashes: null, process: null };
      expect(comparisonEvidence(value, scope)).toMatchObject({ kind: 'verified', ranked: false });
      expect(render(value)).toContain('不会自动重放'); expect(render(value)).not.toContain('基线记录值');
      expect(comparisonEvidence({ ...value, assessment: evidence().assessment }, scope).kind).toBe('invalid');
    }
  });
  it('rejects completion without positive process stop and release proof', () => {
    for (const patch of [{ allStopped: false }, { capacityHeld: true }, { exitCode: 1 }, { executionStatus: 'RUNNING' }]) expect(comparisonEvidence({ ...evidence(), process: { ...evidence().process, ...patch } }, scope).kind).toBe('invalid');
    expect(comparisonEvidence({ ...evidence(), process: null }, scope).kind).toBe('invalid');
  });
  it('handles missing or malformed evidence without implying scientific success', () => {
    expect(comparisonEvidence(undefined, scope).kind).toBe('missing'); expect(render(undefined)).toBe('');
    const html = render({ ...evidence(), input: { malicious: '<script>bad</script>' } });
    expect(html).toContain('不能展示有效评分或排名'); expect(html).not.toContain('<script>');
  });
});
