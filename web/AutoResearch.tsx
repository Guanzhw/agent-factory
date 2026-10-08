import { useEffect, useRef, useState } from 'react';
import { useCommandKeys } from './commandKeys.js';
import { ResearchResponses, researchPointer, researchPresets, researchRun, researchStatus, stepLabels, type AutoResearchApi, type ResearchPointer, type ResearchPreset, type ResearchRun, type StartResearch } from './autoresearchState.js';

const uncertainMessage = '请求结果暂时无法确认。请读取原请求，不要重复开始。';
const limitLabels: Record<string, string> = { maxExperiments: '最多实验', totalSeconds: '总时限（秒）', toolCalls: '最多工具调用', modelRequests: '最多模型请求', modelOutputTokens: '单次输出 token 上限', outputBytes: '输出字节上限', maxIterations: '最多轮次', wallSeconds: '最长运行秒数', experimentSeconds: '实验秒数', maxModelCalls: '最多模型调用', maxOutputTokens: '输出 token 上限' };
export function AutoResearchProgress({ run }: { run: ResearchRun }) {
  const checks = [['modelExecuted', '模型已执行'], ['instructionsRead', '执行指令已读取'], ['agentDecision', '代理已作出决定'], ['managedExperiment', '受管实验已运行'], ['independentResult', '独立结果已记录'], ['nextDecision', '下一步决定已记录']] as const;
  return <section aria-label="研究进展" className="task-panel autoresearch-progress">
    <h2>{researchStatus(run.status)}</h2><p>{run.goal}</p>
    <p>执行完成与科研结论验证分别记录。当前记录不代表科研结论已验证。</p>
    <ul aria-label="执行证据核对">{checks.map(([key, label]) => <li key={key}>{label}：{run.acceptance[key] ? '已记录' : '尚未确认'}</li>)}</ul>
    {run.steps.length ? <ol>{run.steps.map(step => <li key={step.id}><h3>{stepLabels[step.kind]}</h3><p>{step.status === 'observed' ? '已记录' : researchStatus(step.status)}</p><p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{step.text}</p></li>)}</ol> : <p>等待服务器提供实际行动与实验记录。</p>}
    <h3>证据</h3>{run.evidence.length ? <ul>{run.evidence.map((item, index) => <li key={index}>{item.url ? <a href={item.url} download>{item.label}</a> : item.label}</li>)}</ul> : <p>尚无可读取的证据。</p>}
  </section>;
}

export function AutoResearch({ ownerId, api }: { ownerId: string; api: AutoResearchApi }) {
  // Inner key guarantees local state never survives an identity change.
  return <AutoResearchSession key={ownerId} ownerId={ownerId} api={api}/>;
}
function AutoResearchSession({ ownerId, api }: { ownerId: string; api: AutoResearchApi }) {
  const storageKey = `factory-autoresearch-v1:${encodeURIComponent(ownerId)}`;
  const [pointer, setPointer] = useState<ResearchPointer | undefined>(() => { try { return researchPointer(window.sessionStorage.getItem(storageKey)); } catch { return undefined; } });
  const [presets, setPresets] = useState<ResearchPreset[]>([]);
  const [presetId, setPresetId] = useState('');
  const [goal, setGoal] = useState('');
  const [run, setRun] = useState<ResearchRun>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const alive = useRef(true);
  const mutation = useRef(false);
  const uncertain = useRef<StartResearch | undefined>(undefined);
  const responses = useRef(new ResearchResponses());
  const keys = useCommandKeys(ownerId);
  const preset = presets.find(item => item.id === presetId) ?? presets[0];
  function remember(value: ResearchPointer) {
    setPointer(value);
    try { window.sessionStorage.setItem(storageKey, JSON.stringify(value)); } catch { /* Keep current-page recovery. */ }
  }
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    const controller = new AbortController();
    void api.presets(controller.signal).then(value => {
      const current = researchPresets(value);
      if (!controller.signal.aborted) { setPresets(current); setLoaded(true); }
    }).catch(() => { if (!controller.signal.aborted) { setError('暂时无法读取可用研究设置，请重试。'); setLoaded(false); } });
    return () => controller.abort();
  }, [api, refresh]);
  useEffect(() => {
    if (!pointer) return;
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function read() {
      try {
        const raw = await responses.current.read(() => pointer!.runId ? api.get(pointer!.runId, controller.signal) : api.recover(pointer!.requestId, controller.signal), controller.signal);
        if (controller.signal.aborted || raw === undefined) return;
        if (raw === null) { setError('服务器尚未找到原请求。保持原请求待核对；不会自动创建新研究。'); return; }
        const value = researchRun(raw, ownerId, { id: pointer!.runId, requestId: pointer!.requestId });
        if (controller.signal.aborted) return;
        setRun(value); setError('');
        if (!pointer!.runId) remember({ requestId: value.requestId, runId: value.id });
      } catch { if (!controller.signal.aborted) setError('研究状态更新失败，已保留最后确认的记录。请重试。'); }
      if (!controller.signal.aborted) timer = setTimeout(() => void read(), 3000);
    }
    void read(); return () => { controller.abort(); clearTimeout(timer); };
  }, [api, ownerId, pointer, refresh]);
  async function start(useDefault: boolean) {
    if (!preset?.ready || mutation.current || pointer && !uncertain.current || !loaded) return;
    mutation.current = true; responses.current.invalidate(); setBusy(true); setError('');
    try {
      const body = uncertain.current ?? { presetId: preset.id, ...(useDefault ? {} : { goal: goal.trim() }), requestId: (await keys('autoresearch-start', { presetId: preset.id, goal: useDefault ? null : goal.trim() })).requestId };
      if (!alive.current) return;
      uncertain.current = body; remember({ requestId: body.requestId });
      const value = researchRun(await api.start(body), ownerId, body);
      if (!alive.current) return;
      uncertain.current = undefined; setRun(value); remember({ requestId: value.requestId, runId: value.id });
    } catch { if (alive.current) setError(uncertainMessage); }
    finally { mutation.current = false; if (alive.current) { setBusy(false); setRefresh(value => value + 1); } }
  }
  async function cancel() {
    if (!run?.allowedActions.includes('cancel') || mutation.current) return;
    mutation.current = true; responses.current.invalidate(); setBusy(true);
    try {
      const command = await keys('autoresearch-cancel', { id: run.id });
      if (!alive.current) return;
      const value = researchRun(await api.cancel(run.id, { requestId: command.requestId }), ownerId, { id: run.id, requestId: run.requestId });
      if (!alive.current) return;
      setRun(value); setError(''); // Keep stable cancellation key until original run confirms stop.
    } catch { if (alive.current) setError('停止请求尚未确认。请读取原研究状态，资源释放以服务器证据为准。'); }
    finally { mutation.current = false; if (alive.current) { setBusy(false); setRefresh(value => value + 1); } }
  }
  return <section className="autoresearch" aria-labelledby="autoresearch-title">
    <div className="page-heading"><div><h1 id="autoresearch-title">AutoResearch</h1><p>写下研究目标，或按默认目标开始。每一步行动与实验结果都会保留记录。</p></div></div>
    {error && <div role="alert" className="error-message"><p>{error}</p><button className="secondary" onClick={() => setRefresh(value => value + 1)}>读取最新状态</button></div>}
    {!pointer && <section className="composer" aria-label="开始研究">
      {!loaded ? <p>正在读取研究设置…</p> : !preset ? <p>当前没有可用的研究设置。</p> : <>
        {presets.length > 1 ? <label>研究设置<select value={preset.id} onChange={event => setPresetId(event.target.value)} disabled={busy}>{presets.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label> : <h2>{preset.name}</h2>}
        <label>研究目标<textarea value={goal} onChange={event => setGoal(event.target.value)} placeholder={preset.defaultGoal} maxLength={2000} rows={4} disabled={busy}/></label>
        <p>默认目标：{preset.defaultGoal}</p>
        {!!preset.blockers.length && <div role="status"><h3>开始前还需要</h3><ul>{preset.blockers.map((blocker, index) => <li key={index}>{blocker}</li>)}</ul></div>}
        <dl>{Object.entries(preset.limits).map(([key, value]) => <div key={key}><dt>{limitLabels[key] ?? '受管执行上限'}</dt><dd>{value}</dd></div>)}</dl>
        <button className={goal.trim() ? 'primary' : 'secondary'} disabled={!preset.ready || busy || !goal.trim()} onClick={() => void start(false)}>按我的目标开始</button>{' '}
        <button className={goal.trim() ? 'secondary' : 'primary'} disabled={!preset.ready || busy} onClick={() => void start(true)}>按默认目标开始</button>
      </>}
    </section>}
    {pointer && !run && <section aria-label="恢复原研究"><h2>核对原研究请求</h2><p>正在读取服务器记录。此操作不会开始另一项研究。</p><button disabled={busy} onClick={() => setRefresh(value => value + 1)}>读取原请求</button>{uncertain.current && <button disabled={busy} onClick={() => void start(false)}>重试原请求</button>}</section>}
    {run && <><AutoResearchProgress run={run}/>{run.allowedActions.includes('cancel') && <button disabled={busy} onClick={() => void cancel()}>停止研究</button>}<button className="secondary" onClick={() => setRefresh(value => value + 1)}>刷新研究记录</button></>}
  </section>;
}
