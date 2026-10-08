import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { LiteratureEvidencePanel } from '../web/LiteratureEvidence.js';
import { literatureEvidenceState, type LiteratureEvidence } from '../web/literatureEvidenceState.js';
const hash = 'a'.repeat(64);
function evidence(): LiteratureEvidence {
  return { schema: 1, status: 'ready', evidenceKind: 'public_literature_excerpt', mode: 'bibliography-excerpts-no-provider', sourceCount: 1,
    sources: [{ sourceId: 'pmid:123', url: 'https://pubmed.ncbi.nlm.nih.gov/123/', title: '示例文献', textStatus: 'abstract_only', fullTextAvailable: false, missingFullTextReason: 'abstract_only', hashScope: 'metadata_abstract', sha256: hash, excerpt: '摘录🧪', locator: { kind: 'unicode_character_range', field: 'abstract', start: 2, endExclusive: 5, line: 1 } }],
    retrievalErrors: [], reportArtifactId: 'report-id', bundleArtifactId: 'bundle-id' };
}
function render(value?: unknown) { return renderToStaticMarkup(createElement(LiteratureEvidencePanel, { detail: { job: { id: 'task /1' }, literatureEvidence: value } })); }
function invalid(value: unknown) { expect(literatureEvidenceState(value).kind).toBe('invalid'); expect(render(value)).toContain('来源证据尚未核实'); }
describe('literature evidence projection', () => {
  it('keeps legacy missing projections invisible and does not infer evidence from completed status', () => {
    expect(literatureEvidenceState(undefined).kind).toBe('missing'); expect(render()).toBe(''); expect(render(null)).toBe('');
    invalid({ job: { status: 'completed' } });
  });
  it('renders public bounded excerpts with source links, accurate hash scope, and missing full text', () => {
    const html = render(evidence());
    expect(literatureEvidenceState(evidence()).kind).toBe('verified');
    for (const text of ['任务执行完成不代表检索成功', '未调用模型', '未取得全文：仅有摘要', '不是原始论文或 PDF 的哈希', '已记录 1 条来源', '[2, 5)']) expect(html).toContain(text);
    expect(html).toContain('href="https://pubmed.ncbi.nlm.nih.gov/123/"'); expect(html).toContain('rel="noopener noreferrer"');
    expect(html).toContain('/api/factory/jobs/task%20%2F1/artifacts/report-id'); expect(html).toContain('下载证据包');
  });
  it('explicitly distinguishes controlled fixture records from real retrieval', () => {
    const value = evidence(); value.evidenceKind = 'controlled_literature_fixture';
    expect(render(value)).toContain('受控测试样本，不能作为真实在线文献检索证据');
    expect(render(value)).not.toContain('公开文献来源记录；');
  });
  it('shows empty retrieval and finite failure labels without calling it completed research', () => {
    const value = evidence(); value.status = 'no-sources'; value.sources = []; value.sourceCount = 0; value.retrievalErrors = ['COMMAND_FAILED', 'TIMEOUT'];
    expect(render(value)).toContain('不能将空结果当作已完成文献研究'); expect(render(value)).toContain('检索命令失败、检索超时');
    invalid({ ...value, retrievalErrors: ['arbitrary-provider-error'] }); invalid({ ...value, retrievalErrors: ['TIMEOUT', 'TIMEOUT'] });
  });
  it('validates pending and invalid records as empty unknown projections', () => {
    const value = { ...evidence(), status: 'pending', evidenceKind: 'unknown', sourceCount: 0, sources: [], reportArtifactId: null, bundleArtifactId: null };
    expect(render(value)).toContain('来源证据仍待生成或核对'); expect(render(value)).not.toContain('打开来源');
    invalid({ ...value, status: 'invalid' }); invalid({ ...value, sourceCount: 1, sources: evidence().sources }); invalid({ ...value, reportArtifactId: 'report-id' });
  });
  it('rejects non-http links, credentials, control characters, and malformed artifact identifiers', () => {
    for (const url of ['javascript:alert(1)', 'data:text/html,private', 'file:///tmp/a', '//example.com/a', 'https://user:password@example.com/', 'https://example.com/\n']) {
      const value = evidence(); value.sources[0].url = url; invalid(value); expect(render(value)).not.toContain(url);
    }
    invalid({ ...evidence(), reportArtifactId: '../secret' });
  });
  it('escapes untrusted titles and excerpts as text rather than HTML', () => {
    const value = evidence(); value.sources[0].title = '<script>alert(1)</script>'; value.sources[0].excerpt = '<img src=x onerror=alert(1)>';
    value.sources[0].locator.endExclusive = value.sources[0].locator.start + Array.from(value.sources[0].excerpt).length;
    const html = render(value); expect(html).toContain('&lt;script&gt;'); expect(html).toContain('&lt;img'); expect(html).not.toContain('<script>'); expect(html).not.toContain('<img');
  });
  it('rejects mismatched counts, identities, statuses, hashes and full-text claims', () => {
    invalid({ ...evidence(), sourceCount: 0 }); invalid({ ...evidence(), status: 'no-sources' }); invalid({ ...evidence(), evidenceKind: 'unknown' });
    invalid({ ...evidence(), status: ['ready'] }); invalid({ ...evidence(), sourceCount: 4, sources: Array.from({ length: 4 }, () => evidence().sources[0]) });
    invalid({ ...evidence(), sourceCount: 2, sources: [evidence().sources[0], evidence().sources[0]] });
    for (const fields of [{ sha256: 'bad' }, { sha256: null }, { fullTextAvailable: true }, { missingFullTextReason: null }, { hashScope: ['metadata_abstract'] }]) {
      const value = evidence(); Object.assign(value.sources[0], fields); invalid(value);
    }
  });
  it('validates Unicode excerpt ranges and field/hash agreement, without pretending hash recomputation', () => {
    for (const fields of [{ endExclusive: 6 }, { start: -1 }, { line: 0 }, { field: 'stdout' }, { field: ['abstract'] }, { endExclusive: Number.MAX_SAFE_INTEGER + 1 }]) {
      const value = evidence(); Object.assign(value.sources[0].locator, fields); invalid(value);
    }
    const value = evidence(); value.sources[0].missingFullTextReason = 'retrieval_failed'; expect(literatureEvidenceState(value).kind).toBe('verified');
    value.sources[0].excerpt = ''; value.sources[0].sha256 = null; value.sources[0].locator.endExclusive = value.sources[0].locator.start;
    expect(render(value)).toContain('未取得可核对摘录'); expect(render(value)).toContain('未提供，不能核对内容哈希');
  });
  it('labels extracted CLI text without claiming a PDF or model synthesis', () => {
    const value = evidence(); Object.assign(value.sources[0], { textStatus: 'extracted_text', fullTextAvailable: true, missingFullTextReason: null, hashScope: 'decoded_cli_rendition' });
    value.sources[0].locator.field = 'stdout'; expect(render(value)).toContain('抽取文本不等同于原始论文或 PDF'); expect(render(value)).toContain('解码后的 CLI 文本呈现');
  });
});
