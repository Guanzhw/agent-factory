import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { SynthesisJourney } from '../web/SynthesisJourney.js';
import { SynthesisReport, synthesisReportState } from '../web/SynthesisReport.js';
import { saveSynthesisOnce, pendingSynthesisRequest, synthesisPage, synthesisPointerKey, synthesisPreview, synthesisSnapshot, SynthesisJourneyGuard, validateSnapshotReply } from '../web/synthesisJourneyState.js';
const hash = 'a'.repeat(64), otherHash = 'b'.repeat(64);
function projection() { return { schema: 1, status: 'ready', evidenceKind: 'controlled_literature_fixture', mode: 'bibliography-excerpts-no-provider', sourceCount: 1,
  sources: [{ sourceId: 'https://example.org/1', url: 'https://example.org/1', title: '公开合成测试记录', textStatus: 'abstract_only', fullTextAvailable: false, missingFullTextReason: 'abstract_only', hashScope: 'metadata_abstract', sha256: hash, excerpt: 'Synthetic abstract.', locator: { kind: 'unicode_character_range', field: 'abstract', start: 0, endExclusive: 19, line: 1 } }], retrievalErrors: [], reportArtifactId: 'report', bundleArtifactId: 'bundle' }; }
function preview() { return { schema: 1, ownerId: 'alice', sourceTaskId: 'task-1', sourcePlanId: 'plan-1', sourcePlanFingerprint: hash, sourceRunId: 'run-1', fingerprint: hash,
  artifacts: [{ id: 'report', sha256: hash, size: 12 }, { id: 'bundle', sha256: hash, size: 24 }], projection: projection() }; }
function snapshot() { return { ...preview(), id: 'snapshot-1', createdAt: '2026-10-04T00:00:00Z', requestId: 'request-1', question: '比较已取得的来源有哪些限制？', sourceIds: ['https://example.org/1'], sourceFingerprint: hash, contextFingerprint: hash }; }
function evidence() { return { schema: 1, status: 'ready', evidenceKind: 'controlled_model_synthesis', snapshotRef: { id: 'snapshot-1', fingerprint: hash }, snapshotSha256: hash, sourceEvidenceKind: 'controlled_literature_fixture', sourceCurrent: true,
  report: { schema: 1, claims: [{ text: '<script>escaped claim</script>', sourceIds: ['https://example.org/1'], quotes: [{ sourceId: 'https://example.org/1', text: 'Synthetic abstract.' }] }], limitations: ['摘要不能代替全文；需要领域审查。'] }, citationStructureVerified: true, semanticReview: 'required', scientificConclusionVerified: false, artifactIds: { json: 'json-report', markdown: 'md-report' } }; }
describe('source-bound synthesis journey', () => {
  it('checks authoritative source, artifact pins and original owner/task scope', () => {
    expect(synthesisPreview(preview(), 'task-1', 'alice').projection.sourceCount).toBe(1);
    for (const patch of [{ ownerId: 'bob' }, { sourceTaskId: 'other' }, { sourceRunId: null }, { fingerprint: 'bad' }, { artifacts: [{ id: 'report', sha256: hash, size: 12 }] }, { projection: { ...projection(), status: 'pending' } }]) expect(() => synthesisPreview({ ...preview(), ...patch }, 'task-1', 'alice')).toThrow();
  });
  it('recovers historical snapshots read-only without pretending source currentness', () => {
    expect(synthesisSnapshot(snapshot(), 'alice', 'task-1', 'snapshot-1').requestId).toBe('request-1');
    for (const patch of [{ ownerId: 'bob' }, { sourceIds: ['other-source'] }, { contextFingerprint: 'bad' }, { question: '' }, { requestId: '../request' }]) expect(() => synthesisSnapshot({ ...snapshot(), ...patch }, 'alice', 'task-1')).toThrow();
  });
  it('requires a receipt for the original question, source fingerprint, selection and request key', () => {
    const input = { sourceTaskId: 'task-1', sourceIds: snapshot().sourceIds, question: snapshot().question, expectedFingerprint: hash, requestId: 'request-1' };
    expect(validateSnapshotReply(snapshot(), 'alice', input).id).toBe('snapshot-1');
    for (const patch of [{ requestId: 'other' }, { sourceFingerprint: otherHash }, { question: 'different' }]) expect(() => validateSnapshotReply({ ...snapshot(), ...patch }, 'alice', input)).toThrow();
  });
  it('checks owner-scoped bounded pages and exact continuation anchors', () => {
    const page = { schema: 1, ownerId: 'alice', items: [snapshot()], nextCursor: 'snapshot-1', snapshot: false };
    expect(synthesisPage(page, 'alice', 'task-1').nextCursor).toBe('snapshot-1');
    for (const patch of [{ ownerId: 'bob' }, { nextCursor: 'other' }, { items: [snapshot(), snapshot()] }, { snapshot: true }]) expect(() => synthesisPage({ ...page, ...patch }, 'alice', 'task-1')).toThrow();
  });
  it('recovers a lost acknowledgement through GET only and retains unknown outcomes without POST replay', async () => {
    const input = { sourceTaskId: 'task-1', sourceIds: snapshot().sourceIds, question: snapshot().question, expectedFingerprint: hash, requestId: 'request-1' };
    const error = new Error('lost response'); const create = vi.fn().mockRejectedValue(error);
    const list = vi.fn().mockResolvedValue({ schema: 1, ownerId: 'alice', items: [snapshot()], nextCursor: null, snapshot: false });
    expect((await saveSynthesisOnce({ create, list }, 'alice', input)).id).toBe('snapshot-1');
    expect(create).toHaveBeenCalledTimes(1); expect(list).toHaveBeenCalledTimes(1);
    create.mockClear(); list.mockResolvedValue({ schema: 1, ownerId: 'alice', items: [], nextCursor: null, snapshot: false });
    await expect(saveSynthesisOnce({ create, list }, 'alice', input)).rejects.toBe(error);
    expect(create).toHaveBeenCalledTimes(1);
  });
  it('locks double clicks and ignores responses across owner/task switches including ABA', () => {
    const guard = new SynthesisJourneyGuard(); const first = guard.enter('alice', 'task-1');
    expect(guard.claim(first)).toBe(true); expect(guard.claim(first)).toBe(false);
    guard.enter('bob', 'task-1'); const later = guard.enter('alice', 'task-1');
    expect(guard.current(first)).toBe(false); expect(guard.claim(first)).toBe(false); expect(guard.claim(later)).toBe(true);
    guard.release(first); expect(guard.claim(later)).toBe(false); guard.release(later); expect(guard.claim(later)).toBe(true);
  });
  it('stores only owner/task scoped opaque request pointers, not questions or source body', () => {
    expect(synthesisPointerKey('a:b', 'c')).not.toBe(synthesisPointerKey('a', 'b:c'));
    expect(pendingSynthesisRequest('request-1')).toBe('request-1'); expect(pendingSynthesisRequest('{"question":"private"}')).toBeUndefined();
  });
  it('renders no creation or execution on load before server evidence is available', () => {
    const read = vi.fn(), create = vi.fn(), onSnapshot = vi.fn();
    const html = renderToStaticMarkup(createElement(SynthesisJourney, { ownerId: 'alice', sourceTaskId: 'task-1', api: { preview: read, inspect: read, list: read, current: read, create }, onSnapshot }));
    expect(html).toContain('受控模型综合'); expect(html).not.toContain('确认来源并保存快照'); expect(create).not.toHaveBeenCalled(); expect(onSnapshot).not.toHaveBeenCalled();
  });
  it('renders bounded claims as escaped text with explicit scientific limitations and no guessed links', () => {
    expect(synthesisReportState(evidence()).kind).toBe('ready');
    const html = renderToStaticMarkup(createElement(SynthesisReport, { evidence: evidence() }));
    expect(html).toContain('&lt;script&gt;'); expect(html).not.toContain('<script>'); expect(html).not.toContain('href=');
    expect(html).toContain('不等于科研结论验证'); expect(html).toContain('产物列表'); expect(html).toContain('摘要不能代替全文');
  });
  it('keeps historical output visible after source changes and rejects unsupported scientific claims', () => {
    expect(renderToStaticMarkup(createElement(SynthesisReport, { evidence: { ...evidence(), sourceCurrent: false } }))).toContain('保留历史报告');
    for (const patch of [{ scientificConclusionVerified: true }, { semanticReview: 'passed' }, { citationStructureVerified: false }, { snapshotRef: { id: 'snapshot-1', fingerprint: 'bad' } }, { evidenceKind: 'live-science' }]) expect(synthesisReportState({ ...evidence(), ...patch }).kind).toBe('invalid');
    const bad = evidence(); bad.report.claims[0].quotes[0].sourceId = 'unrelated'; expect(synthesisReportState(bad).kind).toBe('invalid');
  });
  it('requires honest pending/invalid envelopes and bounds aggregate quotations', () => {
    const pending = { ...evidence(), status: 'pending', snapshotRef: null, snapshotSha256: null, sourceEvidenceKind: null, sourceCurrent: null, report: null, artifactIds: null, citationStructureVerified: false };
    expect(synthesisReportState(pending).kind).toBe('pending'); expect(synthesisReportState({ ...pending, report: evidence().report }).kind).toBe('invalid');
    const bad = evidence(); bad.report.claims = [1, 2, 3].map(() => ({ text: 'claim', sourceIds: ['source'], quotes: [{ sourceId: 'source', text: 'word '.repeat(8) }] })); expect(synthesisReportState(bad).kind).toBe('invalid');
  });
});
