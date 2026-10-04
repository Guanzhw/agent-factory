import { literatureEvidenceState, type LiteratureTextStatus, type LiteratureRetrievalError } from './literatureEvidenceState.js';
const textStatus: Record<LiteratureTextStatus, string> = {
  extracted_text: '已取得抽取文本', abstract_only: '仅有摘要', metadata_only: '仅有书目信息',
  full_text_unsupported: '当前来源不支持正文提取', retrieval_failed: '正文检索失败', empty_response: '来源返回空文本',
};
const errorNames: Record<LiteratureRetrievalError, string> = { COMMAND_FAILED: '检索命令失败', TIMEOUT: '检索超时', OUTPUT_LIMIT: '返回内容超过上限' };
export function LiteratureEvidencePanel({ detail }: { detail: { job: { id: string }; literatureEvidence?: unknown } }) {
  const state = literatureEvidenceState(detail.literatureEvidence);
  if (state.kind === 'missing') return null;
  if (state.kind === 'invalid') return <section aria-label="文献来源证据"><h3>文献来源证据</h3><p className="error-message" role="alert">来源证据尚未核实，不能据此认定检索成功。请保留任务并核对产物记录。</p></section>;
  const { evidence } = state;
  const artifactUrl = (id: string) => `/api/factory/jobs/${encodeURIComponent(detail.job.id)}/artifacts/${encodeURIComponent(id)}`;
  return <section className="literature-evidence" aria-label="文献来源证据">
    <h3>文献来源证据</h3>
    <p className="quiet">书目与有界摘录模式：未调用模型，不包含模型综合或科研结论。任务执行完成不代表检索成功。</p>
    {evidence.status === 'pending' ? <p role="status">来源证据仍待生成或核对，尚不能确认检索结果。</p> : <>
      <p className={evidence.evidenceKind === 'controlled_literature_fixture' ? 'policy-note' : 'state-note'}>
        {evidence.evidenceKind === 'controlled_literature_fixture' ? '受控测试样本，不能作为真实在线文献检索证据。' : '公开文献来源记录；内容限于实际取得的书目或摘录。'}
      </p>
      {evidence.status === 'no-sources' ? <p className="policy-note" role="status">未取得来源记录（0 条）。不能将空结果当作已完成文献研究。</p> : <p>已记录 {evidence.sourceCount} 条来源。</p>}
      {evidence.retrievalErrors.length > 0 && <p className="policy-note">检索存在失败记录：{evidence.retrievalErrors.map(code => errorNames[code]).join('、')}。已有来源不代表全部检索成功。</p>}
      <ul>{evidence.sources.map(source => <li key={source.sourceId}>
        <h4>{source.title || source.sourceId}</h4>
        <p><a href={source.url} target="_blank" rel="noopener noreferrer">打开来源 {source.sourceId}</a></p>
        <p>{textStatus[source.textStatus]}。{source.fullTextAvailable ? '抽取文本不等同于原始论文或 PDF。' : `未取得全文：${textStatus[source.missingFullTextReason!]}。`}</p>
        {source.excerpt ? <blockquote>{source.excerpt}</blockquote> : <p className="quiet">未取得可核对摘录。</p>}
        <p className="quiet">摘录位置：{source.locator.field === 'abstract' ? '元数据摘要' : 'CLI 文本呈现'}，第 {source.locator.line} 行，Unicode 字符 [{source.locator.start}, {source.locator.endExclusive})。</p>
        <details><summary>来源哈希与覆盖范围</summary><p>哈希范围：{source.hashScope === 'metadata_abstract' ? '元数据摘要' : '解码后的 CLI 文本呈现'}；不是原始论文或 PDF 的哈希。</p><p>SHA-256：{source.sha256 ?? '未提供，不能核对内容哈希'}</p></details>
      </li>)}</ul>
      {(evidence.reportArtifactId || evidence.bundleArtifactId) && <p>
        {evidence.reportArtifactId && <a href={artifactUrl(evidence.reportArtifactId)}>下载来源报告</a>}{' '}
        {evidence.bundleArtifactId && <a href={artifactUrl(evidence.bundleArtifactId)}>下载证据包</a>}
      </p>}
    </>}
  </section>;
}
