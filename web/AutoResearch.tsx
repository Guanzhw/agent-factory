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

export type ResearchReview = { preset: ResearchPreset; goal?: string };
/** Keep the displayed settings fixed until the user explicitly reviews them again. */
export function prepareResearchReview(preset: ResearchPreset | undefined, goal?: string): ResearchReview | undefined {
  if (!preset?.ready || preset.blockers.length || goal !== undefined && (!goal.trim() || goal.trim().length > 2000)) return undefined;
  return { preset: { ...preset, limits: { ...preset.limits }, blockers: [...preset.blockers] }, ...(goal === undefined ? {} : { goal: goal.trim() }) };
}
export function researchReviewMatches(review: ResearchReview, current: ResearchPreset | undefined): boolean {
  if (!current?.ready || current.blockers.length) return false;
  const snapshot = review.preset;
  return snapshot.id === current.id && snapshot.name === current.name && snapshot.defaultGoal === current.defaultGoal
    && snapshot.ready === current.ready && !snapshot.blockers.length
    && JSON.stringify(Object.entries(snapshot.limits).sort()) === JSON.stringify(Object.entries(current.limits).sort());
}
function ResearchLimits({ preset }: { preset: ResearchPreset }) {
  return <><h3>本次执行上限</h3>{Object.keys(preset.limits).length ? <dl>{Object.entries(preset.limits).map(([key, value]) => <div key={key}><dt>{limitLabels[key] ?? '受管执行上限'}</dt><dd>{value}</dd></div>)}</dl> : <p>此设置未提供可显示的执行上限，请先向管理员核对。</p>}</>;
}
function ResearchBlockers({ preset }: { preset: ResearchPreset }) {
  return !!preset.blockers.length && <div role="status"><h3>开始前还需要</h3><ul>{preset.blockers.map((blocker, index) => <li key={index}>{blocker}</li>)}</ul></div>;
}
function ResearchAlternatives({ onRetry, onOpenTasks }: { onRetry: () => void; onOpenTasks?: () => void }) {
  return <div className="actions"><button type="button" className="secondary" onClick={onRetry}>重新读取研究设置</button>{onOpenTasks && <button type="button" className="secondary" onClick={onOpenTasks}>选择其他应用</button>}</div>;
}
export function AutoResearchSetup({ presets, presetId, goal, busy, loading, error, onPreset, onGoal, onReview, onRetry, onOpenTasks }: {
  presets: ResearchPreset[]; presetId: string; goal: string; busy: boolean; loading: boolean; error: string;
  onPreset: (id: string) => void; onGoal: (goal: string) => void; onReview: (useDefault: boolean) => void; onRetry: () => void; onOpenTasks?: () => void;
}) {
  const preset = presets.find(item => item.id === presetId) ?? presets[0];
  const ready = preset?.ready && !preset.blockers.length;
  return <section className="composer" aria-label="准备 Auto-Research 实验">
    {loading ? <p role="status">正在读取研究设置…</p> : error ? <><h2>暂时无法读取研究设置</h2><p role="alert">{error}</p><ResearchAlternatives onRetry={onRetry} onOpenTasks={onOpenTasks}/></> : !preset ? <>
      <h2>Auto-Research 实验尚未配置</h2><p>当前没有可用的研究设置。你可以选择其他已批准的应用，或联系管理员配置 Auto-Research 实验所需的设置与连接。</p>
      <ResearchAlternatives onRetry={onRetry} onOpenTasks={onOpenTasks}/>
    </> : <>
      {presets.length > 1 ? <label>研究设置<select value={preset.id} onChange={event => onPreset(event.target.value)} disabled={busy}>{presets.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label> : <h2>{preset.name}</h2>}
      <label>研究目标<textarea value={goal} onChange={event => onGoal(event.target.value)} placeholder={preset.defaultGoal} maxLength={2000} rows={4} disabled={busy}/></label>
      <p>默认目标：{preset.defaultGoal}</p>
      <ResearchBlockers preset={preset}/><ResearchLimits preset={preset}/>
      {!ready && <><p>此设置暂时不能开始。请联系管理员核对所需条件，或选择其他已批准的应用。</p><ResearchAlternatives onRetry={onRetry} onOpenTasks={onOpenTasks}/></>}
      <p>下一步会显示完整目标与执行上限，确认后才会请求开始。</p>
      <div className="actions"><button type="button" className={goal.trim() ? 'primary' : 'secondary'} disabled={!ready || busy || !goal.trim()} onClick={() => onReview(false)}>检查我的目标</button>
      <button type="button" className={goal.trim() ? 'secondary' : 'primary'} disabled={!ready || busy} onClick={() => onReview(true)}>检查默认目标</button></div>
    </>}
  </section>;
}
export function AutoResearchReview({ review, currentPreset, checking, error, busy, onBack, onStart, onRetry, onOpenTasks }: {
  review: ResearchReview; currentPreset?: ResearchPreset; checking: boolean; error: string; busy: boolean;
  onBack: () => void; onStart: () => void; onRetry: () => void; onOpenTasks?: () => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, []);
  const matches = researchReviewMatches(review, currentPreset);
  return <section className="composer" aria-label="确认 Auto-Research 实验">
    <h2 ref={heading} tabIndex={-1}>开始前确认</h2><p>确认后将按以下设置请求开始研究。实际可用性与执行权限由服务器再次核对。</p>
    <h3>研究设置</h3><p>{review.preset.name}</p><h3>{review.goal === undefined ? '默认研究目标' : '你的研究目标'}</h3><p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{review.goal ?? review.preset.defaultGoal}</p>
    <ResearchLimits preset={review.preset}/><ResearchBlockers preset={review.preset}/>
    {checking ? <p role="status">正在核对研究设置，请稍候。</p> : error ? <p role="alert">{error}</p> : !matches && <div role="alert"><p>研究设置已变化或暂不可用。请返回修改，重新检查当前设置后再开始。</p>{currentPreset && <ResearchBlockers preset={currentPreset}/>}</div>}
    <p>执行记录会显示实际行动、实验结果与证据。执行结束不代表科研结论已验证。</p>
    <div className="actions"><button type="button" className="primary" disabled={busy || checking || !!error || !matches} onClick={onStart}>{busy ? '正在核对并提交…' : '确认并开始研究'}</button><button type="button" className="secondary" disabled={busy} onClick={onBack}>返回修改</button></div>
    {!checking && (error || !matches) && <ResearchAlternatives onRetry={onRetry} onOpenTasks={onOpenTasks}/>}
  </section>;
}

type AutoResearchProps = { ownerId: string; api: AutoResearchApi; onOpenTasks?: () => void; runId?: string; onRun?: (id: string, passive?: boolean) => void };
export function AutoResearch(props: AutoResearchProps) {
  // Neither an identity change nor navigation to another run may retain local state.
  return <AutoResearchSession key={`${props.ownerId}:${props.runId ?? 'entry'}`} {...props}/>;
}
function AutoResearchSession({ ownerId, api, onOpenTasks, runId, onRun }: AutoResearchProps) {
  const storageKey = `factory-autoresearch-v1:${encodeURIComponent(ownerId)}`;
  const [pointer, setPointer] = useState<ResearchPointer | undefined>(() => { try { return researchPointer(window.sessionStorage.getItem(storageKey)); } catch { return undefined; } });
  const [presets, setPresets] = useState<ResearchPreset[]>([]);
  const [presetId, setPresetId] = useState('');
  const [goal, setGoal] = useState('');
  const [review, setReview] = useState<ResearchReview>();
  const [run, setRun] = useState<ResearchRun>();
  const [error, setError] = useState('');
  const [presetsError, setPresetsError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loadingPresets, setLoadingPresets] = useState(true);
  const [refreshPresets, setRefreshPresets] = useState(0);
  const [refreshRun, setRefreshRun] = useState(0);
  const alive = useRef(true);
  const mutation = useRef(false);
  const uncertain = useRef<StartResearch | undefined>(undefined);
  const responses = useRef(new ResearchResponses());
  const onRunRef = useRef(onRun);
  onRunRef.current = onRun;
  const keys = useCommandKeys(ownerId);
  const preset = presets.find(item => item.id === presetId) ?? presets[0];
  const recovering = !!runId || !!pointer;
  function remember(value: ResearchPointer) {
    setPointer(value);
    try { window.sessionStorage.setItem(storageKey, JSON.stringify(value)); } catch { /* Keep current-page recovery. */ }
  }
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoadingPresets(true); setPresetsError('');
    void api.presets(controller.signal).then(value => {
      const current = researchPresets(value);
      if (!controller.signal.aborted) { setPresets(current); setLoadingPresets(false); }
    }).catch(() => { if (!controller.signal.aborted) { setPresetsError('请重新读取研究设置；如果持续失败，请联系管理员。'); setLoadingPresets(false); } });
    return () => controller.abort();
  }, [api, refreshPresets]);
  useEffect(() => {
    if (!runId && !pointer) return;
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    const targetId = runId ?? pointer?.runId;
    async function read() {
      // Do not navigate away from an uncertain in-flight write, even if recovery finds it.
      if (mutation.current) { timer = setTimeout(() => void read(), 3000); return; }
      try {
        const raw = await responses.current.read(() => targetId ? api.get(targetId, controller.signal) : api.recover(pointer!.requestId, controller.signal), controller.signal);
        if (controller.signal.aborted || raw === undefined) return;
        if (raw === null) { setError('服务器尚未找到原请求。保持原请求待核对；不会自动创建新研究。'); return; }
        const value = researchRun(raw, ownerId, { id: targetId, requestId: runId ? undefined : pointer!.requestId });
        if (controller.signal.aborted) return;
        uncertain.current = undefined; setRun(value); setError('');
        if (!runId && (pointer?.runId !== value.id || pointer?.requestId !== value.requestId)) remember({ requestId: value.requestId, runId: value.id });
        onRunRef.current?.(value.id, true);
      } catch { if (!controller.signal.aborted) setError('研究状态暂时无法读取或核对，已保留最后确认的记录。请重试；持续失败时请联系管理员。'); }
      if (!controller.signal.aborted) timer = setTimeout(() => void read(), 3000);
    }
    void read(); return () => { controller.abort(); clearTimeout(timer); };
  }, [api, ownerId, pointer, runId, refreshRun]);
  function checkGoal(useDefault: boolean) {
    if (mutation.current || recovering || loadingPresets || presetsError) return;
    const next = prepareResearchReview(preset, useDefault ? undefined : goal);
    if (next) { setError(''); setReview(next); }
  }
  async function start(confirmed?: ResearchReview) {
    if (mutation.current || runId) return;
    if (confirmed ? pointer || loadingPresets || presetsError || !researchReviewMatches(confirmed, presets.find(item => item.id === confirmed.preset.id)) : !uncertain.current || run) return;
    mutation.current = true; responses.current.invalidate(); setBusy(true); setError('');
    try {
      if (confirmed) {
        // Recheck the displayed configuration immediately before the first write.
        // The current API has no atomic preset revision pin; the server still rechecks execution.
        let current: ResearchPreset[];
        try { current = researchPresets(await api.presets()); }
        catch { if (alive.current) setPresetsError('开始前无法核对最新研究设置。请重新读取后再确认。'); return; }
        if (!alive.current) return;
        setPresets(current); setPresetsError('');
        if (!researchReviewMatches(confirmed, current.find(item => item.id === confirmed.preset.id))) {
          return;
        }
      }
      const body = uncertain.current ?? { presetId: confirmed!.preset.id, ...(confirmed!.goal === undefined ? {} : { goal: confirmed!.goal }), requestId: (await keys('autoresearch-start', { presetId: confirmed!.preset.id, goal: confirmed!.goal ?? null })).requestId };
      if (!alive.current) return;
      uncertain.current = body; remember({ requestId: body.requestId });
      const value = researchRun(await api.start(body), ownerId, body);
      if (!alive.current) return;
      uncertain.current = undefined; setRun(value); remember({ requestId: value.requestId, runId: value.id });
      onRunRef.current?.(value.id);
    } catch { if (alive.current) setError(uncertain.current ? uncertainMessage : '开始请求尚未发送。请重试确认。'); }
    finally { mutation.current = false; if (alive.current) { setBusy(false); setRefreshRun(value => value + 1); } }
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
    finally { mutation.current = false; if (alive.current) { setBusy(false); setRefreshRun(value => value + 1); } }
  }
  return <section className="autoresearch" aria-labelledby="autoresearch-title">
    <div className="page-heading"><div><h1 id="autoresearch-title">Auto-Research 实验</h1><p>写下研究目标，检查设置与执行上限，再确认开始。每一步行动与实验结果都会保留记录。</p></div></div>
    {error && <div role="alert" className="error-message"><p>{error}</p>{recovering && <button type="button" className="secondary" onClick={() => setRefreshRun(value => value + 1)}>读取最新状态</button>}</div>}
    {!recovering && (review ? <AutoResearchReview review={review} currentPreset={presets.find(item => item.id === review.preset.id)} checking={loadingPresets} error={presetsError} busy={busy} onBack={() => setReview(undefined)} onStart={() => void start(review)} onRetry={() => setRefreshPresets(value => value + 1)} onOpenTasks={onOpenTasks}/> : <AutoResearchSetup presets={presets} presetId={presetId} goal={goal} busy={busy} loading={loadingPresets} error={presetsError} onPreset={setPresetId} onGoal={setGoal} onReview={checkGoal} onRetry={() => setRefreshPresets(value => value + 1)} onOpenTasks={onOpenTasks}/>)}
    {recovering && !run && <section aria-label="恢复原研究"><h2>{runId ? '读取已有研究' : '核对原研究请求'}</h2><p>正在读取服务器记录。此操作不会开始另一项研究。</p><button type="button" disabled={busy} onClick={() => setRefreshRun(value => value + 1)}>读取原请求</button>{uncertain.current && <button type="button" disabled={busy} onClick={() => void start()}>重试原请求</button>}{onOpenTasks && <button type="button" className="secondary" disabled={busy} onClick={onOpenTasks}>选择其他应用</button>}</section>}
    {run && <><AutoResearchProgress run={run}/>{!runId && onRun && <button type="button" className="secondary" disabled={busy} onClick={() => onRun(run.id)}>打开研究记录</button>}{run.allowedActions.includes('cancel') && <button type="button" disabled={busy} onClick={() => void cancel()}>停止研究</button>}<button type="button" className="secondary" onClick={() => setRefreshRun(value => value + 1)}>刷新研究记录</button></>}
  </section>;
}
