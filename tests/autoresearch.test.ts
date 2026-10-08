import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { AutoResearchProgress, AutoResearch } from '../web/AutoResearch.js';
import { researchPresets, researchRun, researchPointer, ResearchResponses, type AutoResearchApi } from '../web/autoresearchState.js';
const acceptance = { modelExecuted: false, instructionsRead: false, agentDecision: false, managedExperiment: false, independentResult: false, nextDecision: false, scientificConclusionVerified: false };
const fixture = () => ({ id: 'run-one', ownerId: '研究员@example.org', requestId: 'request-one', presetId: 'preset-one', goal: '验证公开实验问题', status: 'completed', steps: [{ id: 'one', kind: 'assessment', status: 'waiting', text: '尚无独立验证结果<script>bad</script>' }], evidence: [{ label: '待确认' }], allowedActions: [], acceptance: { ...acceptance } });
describe('AutoResearch owner-bound projections', () => {
  it('preserves actual evidence and never promotes execution completion to scientific acceptance', () => {
    const raw = fixture(); const value = researchRun(raw, raw.ownerId, { id: raw.id, requestId: raw.requestId });
    raw.acceptance.modelExecuted = true;
    expect(value.acceptance.modelExecuted).toBe(false);
    const html = renderToStaticMarkup(createElement(AutoResearchProgress, { run: value }));
    expect(html).toContain('执行结束'); expect(html).toContain('不代表科研结论已验证'); expect(html).toContain('尚未确认');
    expect(html).not.toContain('<script>'); expect(html).not.toContain('run-one');
  });
  it('rejects wrong owners, replaced runs, changed requests, and scientific success claims', () => {
    const raw = fixture();
    expect(() => researchRun(raw, 'bob')).toThrow();
    expect(() => researchRun(raw, raw.ownerId, { id: 'other' })).toThrow();
    expect(() => researchRun(raw, raw.ownerId, { requestId: 'other' })).toThrow();
    expect(() => researchRun({ ...raw, acceptance: { ...acceptance, scientificConclusionVerified: true } }, raw.ownerId)).toThrow();
    expect(() => researchRun({ ...raw, acceptance: { ...acceptance, modelExecuted: 'true' } }, raw.ownerId)).toThrow();
  });
  it('rejects provider/auth/external evidence links and malformed histories', () => {
    const raw = fixture();
    for (const url of ['https://external.test/private', '//external.test', '/api/factory/auth/login', '/api/factory/artifacts/../auth', '/api/factory/jobs/foreign/artifacts/report', '/api/factory/jobs/run-one/artifacts/../auth', '/api/factory/jobs/run-one/artifacts/report?redirect=evil', '/api/factory/jobs/run-one/artifacts/%2e%2e', 'javascript:alert(1)']) {
      expect(() => researchRun({ ...raw, evidence: [{ label: 'file', url }] }, raw.ownerId)).toThrow();
    }
    const url = '/api/factory/jobs/run-one/artifacts/report-one';
    expect(researchRun({ ...raw, evidence: [{ label: '研究报告', url }] }, raw.ownerId).evidence).toEqual([{ label: '研究报告', url }]);
    expect(() => researchRun({ ...raw, steps: [raw.steps[0], raw.steps[0]] }, raw.ownerId)).toThrow();
    expect(() => researchRun({ ...raw, allowedActions: ['publish'] }, raw.ownerId)).toThrow();
  });
  it('checks preset readiness, finite limits and duplicate identities', () => {
    const preset = { id: 'bounded', name: '受管研究', defaultGoal: '公开问题', ready: false, blockers: ['尚未配置研究连接'], limits: { maxIterations: 1 } };
    expect(researchPresets([preset])[0].ready).toBe(false);
    expect(() => researchPresets([{ ...preset, ready: 'true' }])).toThrow();
    expect(() => researchPresets([{ ...preset, limits: { maxIterations: Infinity } }])).toThrow();
    expect(() => researchPresets([preset, preset])).toThrow();
  });
  it('retains only opaque recovery pointers and rejects invalid pointer data', () => {
    expect(researchPointer(JSON.stringify({ requestId: 'request-one', runId: 'run-one', goal: 'not retained' }))).toEqual({ requestId: 'request-one', runId: 'run-one' });
    expect(researchPointer('{bad')).toBeUndefined(); expect(researchPointer('{"requestId":"../foreign"}')).toBeUndefined();
  });
  it('drops late responses/errors after identity invalidation even if transport ignores abort', async () => {
    const requests = new ResearchResponses(); let resolve!: (value: string) => void;
    const old = requests.read(() => new Promise<string>(done => { resolve = done; }));
    requests.invalidate(); const current = await requests.read(async () => 'bob'); resolve('alice');
    expect(current).toBe('bob'); expect(await old).toBeUndefined();
    const controller = new AbortController(); controller.abort(); expect(await requests.read(async () => 'old', controller.signal)).toBeUndefined();
  });
  it('initial render exposes no backend identifiers or start before readiness', () => {
    const unavailable = async () => { throw new Error('must not call during render'); };
    const api: AutoResearchApi = { presets: unavailable, start: unavailable, get: unavailable, recover: unavailable, cancel: unavailable };
    const html = renderToStaticMarkup(createElement(AutoResearch, { ownerId: 'private-owner', api }));
    expect(html).toContain('Auto-Research 实验'); expect(html).toContain('正在读取研究设置');
    expect(html).not.toContain('private-owner'); expect(html).not.toContain('/api/');
  });
});
