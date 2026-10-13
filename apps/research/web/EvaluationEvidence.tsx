import { evaluationEvidence, type JobDetail } from '../../../web/models.js';

export function EvaluationEvidence({ detail }: { detail: JobDetail }) {
  const evidence = evaluationEvidence(detail);
  if (!evidence) return <section><h3>评估证据</h3><p className="list-empty">后端尚未提供评估记录。</p></section>;
  const scalar = (key: string) => {
    const value = evidence[key];
    return typeof value === 'string' || (typeof value === 'number' && Number.isFinite(value)) ? String(value) : '未提供';
  };
  const synthetic = evidence.evidenceKind === 'synthetic';
  const suffix = synthetic ? '（合成）' : '（证据类型待核实）';
  const metricNames: Record<string, string> = { inversion_count: '逆序对数量' };
  const directions: Record<string, string> = { lower: '数值越低越好', higher: '数值越高越好' };
  return <section><div className="section-heading"><h3>评估证据</h3><span className="quiet">{synthetic ? '合成评估记录' : scalar('evidenceKind')}</span></div><p className="quiet">以下为后端记录的评估值，不据此认定真实研究改进。</p><dl className="execution-metrics">{([['baseline', '基线值'], ['candidate', '候选值'], ['delta', '差值'], ['elapsedSeconds', '评估耗时（秒）']] as const).map(([key, label]) => <div key={key}><dt>{label}{suffix}</dt><dd>{scalar(key)}</dd></div>)}</dl><dl className="plan-details"><dt>评估指标{suffix}</dt><dd>{metricNames[scalar('metric')] ?? scalar('metric')}</dd><dt>指标方向{suffix}</dt><dd>{directions[scalar('direction')] ?? scalar('direction')}</dd></dl><details className="technical-detail"><summary>评估器与证据来源</summary>{([['evaluatorId', '评估器'], ['evaluatorVersion', '评估器版本'], ['datasetHash', '数据集哈希'], ['outputHash', '输出哈希'], ['runtimeId', '运行环境'], ['modelId', '模型'], ['evidenceKind', '证据类型']] as const).map(([key, label]) => <span key={key}>{label}：{scalar(key)}</span>)}</details></section>;
}
