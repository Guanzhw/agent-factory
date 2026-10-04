import { useEffect, useRef, useState } from 'react';
import { comparisonCatalog, comparisonEvidence, type ComparisonInputManifest, type ComparisonItem, type ComparisonSeed } from './comparisonState.js';
export type { ComparisonSeed } from './comparisonState.js';
export interface ComparisonPanelProps { ownerId: string; api: { catalog(signal?: AbortSignal): Promise<unknown> }; onPrepare: (seed: ComparisonSeed) => void; disabled?: boolean }
const choiceNames: Record<string, string> = { 'linear-v1': '线性候选', 'constant-v1': '常量候选', 'offset-v1': '偏移候选', 'failure-v1': '评估器失败情景', 'long-running-v1': '长运行与停止情景' };
function InputSummary({ input }: { input: ComparisonInputManifest }) {
  const changed = Object.keys(input.baselineFiles).filter(path => input.baselineFiles[path] !== input.candidateFiles[path]);
  return <div><p>候选：{choiceNames[input.choice] ?? input.choice} · 合成开发数据，不是实际科研数据集。</p>
    <dl className="plan-details"><dt>固定数据集</dt><dd>{input.dataset.path} · {input.dataset.sampleCount} 个样本 · {input.dataset.license}</dd><dt>固定评估器</dt><dd>{input.evaluator.path} · {input.evaluator.protocolRevision}</dd><dt>比较指标</dt><dd>{input.metric.id}（{input.metric.unit}）；{input.metric.direction === 'minimize' ? '越小越好' : '越大越好'}；变化阈值 {input.metric.minimumImprovement}</dd><dt>允许修改的文件</dt><dd>{input.allowedChanges.join('、')}</dd><dt>本候选实际变更</dt><dd>{changed.length ? changed.join('、') : '没有文件变化'}</dd><dt>固定运行边界</dt><dd>CPU {input.resourceLimits.cpu} · 内存 {input.resourceLimits.memoryMb} MiB · 时长 {input.resourceLimits.wallSeconds} 秒 · 输出 {input.resourceLimits.outputBytes} 字节</dd></dl>
    <p className="quiet">候选不能更换数据、评估器或扩大允许修改范围。限额声明不等于操作系统安全沙箱；执行与停止证据单独记录。</p>
    <details className="technical-detail"><summary>基线、候选与来源指纹</summary><span>数据 SHA-256 {input.dataset.sha256}</span><span>样本集 SHA-256 {input.dataset.sampleSetSha256}</span><span>评估器 SHA-256 {input.evaluator.sha256}</span><span>固定种子 {input.seed}</span>{Object.keys(input.baselineFiles).map(path => <div key={path}><strong>{path}</strong><p>基线 {input.baselineFiles[path]}</p><p>候选 {input.candidateFiles[path]}</p></div>)}</details>
  </div>;
}
export function ComparisonPanel({ ownerId, api, onPrepare, disabled = false }: ComparisonPanelProps) {
  const transport = useRef(api); transport.current = api; const generation = useRef(0);
  const [loaded, setLoaded] = useState<{ owner: string; items: ComparisonItem[] }>(); const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(true); const [error, setError] = useState(''); const [refresh, setRefresh] = useState(0);
  const items = loaded?.owner === ownerId ? loaded.items : undefined;
  const key = (item: ComparisonItem) => `${item.applicationRef.id}@${item.applicationRef.version}:${item.applicationRef.sha256}:${item.mode}`;
  const item = items?.find(item => key(item) === selected);
  useEffect(() => {
    const controller = new AbortController(); const version = ++generation.current; setLoaded(undefined); setSelected(''); setBusy(true); setError('');
    void transport.current.catalog(controller.signal).then(value => {
      const items = comparisonCatalog(value, ownerId);
      if (!controller.signal.aborted && generation.current === version) setLoaded({ owner: ownerId, items });
    }).catch(() => { if (!controller.signal.aborted && generation.current === version) setError('当前已批准比较应用或固定输入无法核对，请刷新目录。'); })
      .finally(() => { if (!controller.signal.aborted && generation.current === version) setBusy(false); });
    return () => { controller.abort(); generation.current++; };
  }, [ownerId, refresh]);
  return <section className="comparison-panel" aria-label="受控基线候选比较" style={{ minWidth: 0, overflowWrap: 'anywhere' }}><h2>准备基线与候选比较</h2>
    <p className="state-note">合成开发数据与已审阅的固定程序，仅验证比较工作流。结果不是非 toy 科研验收，也不能据此证明科学结论。</p>
    <button type="button" className="secondary" disabled={disabled || busy} onClick={() => setRefresh(n => n + 1)}>刷新比较目录</button>
    {error && <p role="alert" className="error-message">{error}</p>}{busy && <p role="status">正在核对已批准的比较范围…</p>}
    <label>比较候选<select aria-label="比较候选" disabled={disabled || busy || !items?.length} value={item ? selected : ''} onChange={event => setSelected(event.target.value)}><option value="">选择固定比较情景</option>{items?.map(item => <option key={key(item)} value={key(item)}>{item.name} · {choiceNames[item.input.choice] ?? item.input.choice}</option>)}</select></label>
    {items?.length === 0 && <p>当前没有可用的已批准比较应用，请由管理员先完成定义治理。</p>}
    {item && <><h3>{item.goal}</h3><InputSummary input={item.input}/><p>下一步生成装配提案并审查不可变方案。这里不会启动进程；执行、停止、产物校验与比较结果分别确认。</p>
      <button type="button" className="primary" disabled={disabled || busy} onClick={() => { if (!disabled && !busy && loaded?.owner === ownerId) onPrepare(structuredClone({ applicationRef: item.applicationRef, mode: item.mode, goal: item.goal, input: item.input })); }}>用此比较准备方案</button></>}
  </section>;
}
export interface ComparisonReportProps { evidence: unknown; ownerId: string; taskId: string; planId: string; artifacts: { id: string; sha256?: string; size?: number }[] }
const statuses = { pending: '等待比较证据', ready: '原执行与产物已核对', failed: '原执行失败', cancelled: '原执行已取消', unknown: 'UNKNOWN · 原执行待核对', invalid: '比较证据无效' };
const assessments = { improved: '候选指标改善', regressed: '候选指标退化', unchanged: '未超过预定变化阈值', inconclusive: '无法比较' };
export function ComparisonReport(props: ComparisonReportProps) {
  const state = comparisonEvidence(props.evidence, props);
  if (state.kind === 'missing') return null;
  if (state.kind === 'invalid') return <section aria-label="基线候选比较证据"><h3>基线候选比较证据</h3><p role="alert">任务、输入或产物指纹未完整核对，不能展示有效评分或排名。</p></section>;
  const value = state.evidence;
  return <section className="comparison-report" aria-label="基线候选比较证据" style={{ minWidth: 0, overflowWrap: 'anywhere' }}><h3>基线候选比较证据</h3><p className="state-note">合成开发数据的受控比较，不是科学结论。原生任务完成、评估器结果和资源释放分别核对。</p><p role="status">{statuses[value.status]}</p>
    {value.input && <InputSummary input={value.input}/>}
    {state.ranked && value.assessment && <><h4>{assessments[value.assessment.status]}</h4><dl className="execution-metrics"><div><dt>基线记录值</dt><dd>{value.baseline!.value}</dd></div><div><dt>候选记录值</dt><dd>{value.candidate!.value}</dd></div><div><dt>按指标方向计算的改善值</dt><dd>{value.assessment.improvement}</dd></div></dl><p className="quiet">仅描述同一固定样本集、评估器和指标的差异，不代表统计显著性或科学有效性。</p></>}
    {!state.ranked && <p className="policy-note">未形成可比较的完整结果，不排名、不推算分数。失败、取消或 UNKNOWN 不会自动重放；请使用原任务的核对与取消入口。</p>}
    {value.assessment?.status === 'inconclusive' && <p>评估未完成：基线 {value.baseline?.status} · 候选 {value.candidate?.status}。工作流产物已核对不代表双方评估成功。</p>}
    {value.process && <p>{value.process.allStopped ? '已记录原进程停止证据。' : '原进程停止尚未确认。'} {value.process.capacityHeld ? '预约容量仍保留。' : '服务端记录预约容量已释放。'} 进程状态 {value.process.executionStatus}{value.process.exitCode !== null ? ` · 退出码 ${value.process.exitCode}` : ''}</p>}
    <p className="quiet">下载与校验使用本任务的产物列表；读取证据不会启动新运行。</p>
    <details className="technical-detail"><summary>原运行与评估凭据</summary><span>任务 {value.taskId}</span><span>方案 {value.planId}</span><span>原生运行 {value.nativeRunId ?? '尚未确认'}</span><span>比较契约 {value.contractSha256 ?? '未核对'}</span><span>候选契约 {value.candidateSha256 ?? '未核对'}</span>{value.artifactIds && <><span>原始输出 {value.artifactIds.raw}</span><span>比较报告 {value.artifactIds.report}</span></>}</details>
  </section>;
}
