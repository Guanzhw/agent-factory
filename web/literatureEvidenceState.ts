export type LiteratureTextStatus = 'extracted_text' | 'abstract_only' | 'metadata_only' | 'full_text_unsupported' | 'retrieval_failed' | 'empty_response';
export type LiteratureRetrievalError = 'COMMAND_FAILED' | 'TIMEOUT' | 'OUTPUT_LIMIT';
export interface LiteratureSource {
  sourceId: string; url: string; title: string; textStatus: LiteratureTextStatus; fullTextAvailable: boolean;
  missingFullTextReason: Exclude<LiteratureTextStatus, 'extracted_text'> | null;
  hashScope: 'decoded_cli_rendition' | 'metadata_abstract'; sha256: string | null; excerpt: string;
  locator: { kind: 'unicode_character_range'; field: 'abstract' | 'stdout'; start: number; endExclusive: number; line: number };
}
export interface LiteratureEvidence {
  schema: 1; status: 'ready' | 'no-sources' | 'invalid' | 'pending';
  evidenceKind: 'public_literature_excerpt' | 'controlled_literature_fixture' | 'unknown';
  mode: 'bibliography-excerpts-no-provider'; sourceCount: number; sources: LiteratureSource[];
  retrievalErrors: LiteratureRetrievalError[]; reportArtifactId: string | null; bundleArtifactId: string | null;
}
export type LiteratureEvidenceState = { kind: 'missing' } | { kind: 'invalid' } | { kind: 'verified'; evidence: LiteratureEvidence };
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const integer = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const text = (value: unknown, max: number): value is string => typeof value === 'string' && Array.from(value).length <= max;
const identifier = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value);
const statuses = new Set<unknown>(['extracted_text', 'abstract_only', 'metadata_only', 'full_text_unsupported', 'retrieval_failed', 'empty_response']);
const errors = new Set<unknown>(['COMMAND_FAILED', 'TIMEOUT', 'OUTPUT_LIMIT']);
function source(value: unknown): value is LiteratureSource {
  if (!record(value) || !text(value.sourceId, 320) || !value.sourceId || /\s/.test(value.sourceId)
      || !text(value.url, 2048) || !text(value.title, 240) || !statuses.has(value.textStatus)
      || typeof value.fullTextAvailable !== 'boolean' || value.fullTextAvailable !== (value.textStatus === 'extracted_text')
      || (value.fullTextAvailable ? value.missingFullTextReason !== null
        : !statuses.has(value.missingFullTextReason) || value.missingFullTextReason === 'extracted_text')
      || typeof value.hashScope !== 'string' || !['decoded_cli_rendition', 'metadata_abstract'].includes(value.hashScope)
      || !(value.sha256 === null || typeof value.sha256 === 'string' && /^[a-f0-9]{64}$/.test(value.sha256))
      || !text(value.excerpt, 160) || value.sha256 === null && value.excerpt !== '' || !record(value.locator)) return false;
  // React escapes text; URLs additionally need an explicit safe scheme and no credentials.
  if (Array.from(value.url).some(char => char.charCodeAt(0) <= 32 || char.charCodeAt(0) === 127)) return false;
  try {
    const url = new URL(value.url);
    if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password) return false;
  } catch { return false; }
  const locator = value.locator;
  return locator.kind === 'unicode_character_range' && typeof locator.field === 'string' && ['abstract', 'stdout'].includes(locator.field)
    && value.hashScope === (locator.field === 'abstract' ? 'metadata_abstract' : 'decoded_cli_rendition')
    && integer(locator.start) && integer(locator.endExclusive) && locator.endExclusive >= locator.start
    && locator.endExclusive - locator.start === Array.from(value.excerpt).length
    && integer(locator.line) && locator.line >= 1
    && locator.start <= 2 * 1024 * 1024 && locator.endExclusive <= 2 * 1024 * 1024 && locator.line <= 2 * 1024 * 1024;
}
export function literatureEvidenceState(value: unknown): LiteratureEvidenceState {
  if (value === undefined || value === null) return { kind: 'missing' };
  if (!record(value) || value.schema !== 1 || value.mode !== 'bibliography-excerpts-no-provider'
      || typeof value.status !== 'string' || !['ready', 'no-sources', 'invalid', 'pending'].includes(value.status)
      || typeof value.evidenceKind !== 'string' || !['public_literature_excerpt', 'controlled_literature_fixture', 'unknown'].includes(value.evidenceKind)
      || !integer(value.sourceCount) || value.sourceCount > 3 || !Array.isArray(value.sources)
      || value.sourceCount !== value.sources.length || !value.sources.every(source)
      || new Set(value.sources.map(item => item.sourceId)).size !== value.sourceCount
      || !Array.isArray(value.retrievalErrors) || value.retrievalErrors.length > 3
      || !value.retrievalErrors.every(error => errors.has(error)) || new Set(value.retrievalErrors).size !== value.retrievalErrors.length
      || !(value.reportArtifactId === null || identifier(value.reportArtifactId))
      || !(value.bundleArtifactId === null || identifier(value.bundleArtifactId))) return { kind: 'invalid' };
  if (value.status === 'invalid' || value.status === 'pending') {
    if (value.sourceCount !== 0 || value.evidenceKind !== 'unknown' || value.reportArtifactId !== null || value.bundleArtifactId !== null || value.retrievalErrors.length !== 0) return { kind: 'invalid' };
    if (value.status === 'invalid') return { kind: 'invalid' };
  } else if (value.evidenceKind === 'unknown' || (value.status === 'ready' ? value.sourceCount === 0 : value.sourceCount !== 0)) return { kind: 'invalid' };
  return { kind: 'verified', evidence: value as unknown as LiteratureEvidence };
}
