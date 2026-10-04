import type { ComparisonSeed } from './ComparisonPanel.js';
import { sameSourceSnapshot } from './sourcePlanState.js';
import { useEffect, useRef, useState } from 'react';
import type { SynthesisSnapshot } from './synthesisJourneyState.js';
import { api, ApiError } from './api.js';
import { useCommandKeys } from './commandKeys.js';
import { PlanReviewGate } from './PlanReviews.js';
import { CompositionInbox } from './CompositionInbox.js';
import { UsageCommitmentSummary } from './UsageLedger.js';
import { usageCommitment } from './usageLedgerState.js';
import { kindNames, materialKey, type AssemblyProposal, type CompositionInput, type ExecutionTarget, type FactoryApplication, type FactoryMaterial, type MaterialReference, type Plan, type User, type UserConnection } from './models.js';

type Act = (name: string, work: () => Promise<void>) => Promise<void>;
const message = (e: unknown) => e instanceof Error ? e.message : '装配状态无法确认。';
const refKey = (ref: MaterialReference) => `${materialKey(ref)}:${ref.sha256}`;
const modeName = (value: string) => ({ literature: '文献与证据', experiment: '实验探索', success: '真实 ORX toy 成功评估', evaluator_failure: '真实 ORX 评估器失败验收', cancellable: '真实 ORX 运行中取消验收' } as Record<string, string>)[value] ?? value;
const budgetNames: Record<string, string> = { toolCalls: '工具调用', maxDepth: '最大委派深度', maxChildren: '累计子任务', experimentSeconds: '实验秒数', outputBytes: '产物字节' };

function adapterNames(bindings: Record<string, unknown> | null): string[] {
  if (!bindings) return [];
  const values = [bindings.model, bindings.environment, ...(Array.isArray(bindings.tools) ? bindings.tools : []), ...(Array.isArray(bindings.knowledge) ? bindings.knowledge : [])];
  return values.flatMap(value => value && typeof value === 'object' && typeof value.adapterId === 'string' && typeof value.revision === 'string' ? [`${value.adapterId}@${value.revision}`] : []);
}
export function ApplicationComposer({ user, busy, act, materials, targets, onCreated, sourceSeed, onSchedule, comparisonSeed }: { comparisonSeed?: ComparisonSeed; onSchedule?: (plan: Plan) => void; sourceSeed?: SynthesisSnapshot; user: User; busy: string; act: Act; materials: FactoryMaterial[]; targets: ExecutionTarget[]; onCreated: (id: string) => void }) {
  const [applications, setApplications] = useState<FactoryApplication[]>([]);
  const [connections, setConnections] = useState<UserConnection[]>([]);
  const [applicationId, setApplicationId] = useState(comparisonSeed?.applicationRef.id ?? (sourceSeed ? 'source-grounded-synthesis-fixture-v1' : ''));
  const [mode, setMode] = useState(comparisonSeed?.mode ?? '');
  const [comparisonRef, setComparisonRef] = useState(comparisonSeed?.applicationRef);
  const [goal, setGoal] = useState(comparisonSeed?.goal ?? sourceSeed?.question ?? '');
  const [sourceRef, setSourceRef] = useState<CompositionInput['sourceSnapshotRef']>(sourceSeed ? { id: sourceSeed.id, fingerprint: sourceSeed.fingerprint } : undefined);
  const [choices, setChoices] = useState<Record<string, MaterialReference>>({});
  const [connectionRefs, setConnectionRefs] = useState<Record<string, string>>({});
  const pointerKey = `factory-proposal-v1:${encodeURIComponent(user.id)}`;
  const [storedProposal] = useState(() => { if (sourceSeed || comparisonSeed) return undefined; try { const id = window.sessionStorage.getItem(pointerKey); return id && /^[a-f0-9-]{36}$/.test(id) ? id : undefined; } catch { return undefined; } });
  const [proposal, setProposal] = useState<AssemblyProposal>();
  const [restored, setRestored] = useState(false);
  function rememberProposal(value?: AssemblyProposal) { try { if (value) window.sessionStorage.setItem(pointerKey, value.id); else window.sessionStorage.removeItem(pointerKey); } catch { /* Persist only an opaque owner-scoped pointer when storage is available. */ } }
  const [plan, setPlan] = useState<Plan>();
  const [executionAllowed, setExecutionAllowed] = useState(false);
  const [target, setTarget] = useState('');
  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const uncertainRevision = useRef<{ id?: string; input: CompositionInput; requestId: string } | undefined>(undefined);
  const keys = useCommandKeys(user.id);
  const application = applications.find(item => item.id === applicationId && (!comparisonRef || refKey(item) === refKey(comparisonRef)));
  const comparisonStale = !!comparisonRef && !application;
  const selectedMode = application?.modes[mode || application.defaultMode];
  const accepted = !!plan || proposal?.state === 'accepted';
  const pending = proposal?.state === 'pending';
  useEffect(() => {
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const [session, apps, refs, loaded] = await Promise.all([api.session(controller.signal), api.applications(controller.signal), api.userConnections(controller.signal), proposal?.id || !restored && storedProposal ? api.recoverProposal(proposal?.id ?? storedProposal!, controller.signal) : Promise.resolve(undefined)]);
        let current = loaded?.proposal;
        let historicalPlan = loaded?.plan;
        if (!proposal && !restored) {
          const seen = new Set<string>();
          for (let depth = 0; current?.state === 'revised' && current.revisedBy && depth < 8; depth++) {
            if (current.ownerId !== user.id || seen.has(current.id) || !/^[a-f0-9-]{36}$/.test(current.revisedBy)) throw new Error('修订恢复指针无法核对。');
            seen.add(current.id); const previous = current.id; const recovered = await api.recoverProposal(current.revisedBy, controller.signal); const successor = recovered.proposal; historicalPlan = recovered.plan;
            if (successor.parentId !== previous || successor.ownerId !== user.id) throw new Error('修订恢复范围无法核对。');
            current = successor; rememberProposal(current);
          }
        }
        if (session.id !== user.id || refs.some(item => item.ownerId !== user.id) || current && current.ownerId !== user.id) throw new Error('当前身份或提案归属无法核对；暂时禁用装配。');
        if (controller.signal.aborted) return;
        setApplications(apps); setConnections(refs); if (current) { if (!proposal) { setGoal(current.candidate.normalizedGoal); setSourceRef(current.input.sourceSnapshotRef); setApplicationId(current.candidate.application); setMode(current.candidate.mode); setChoices(current.input.materialChoices ?? {}); setConnectionRefs(current.input.connectionRefs ?? {}); } setProposal(current); setPlan(historicalPlan ?? undefined); } setRestored(true); setReady(true); setError('');
      } catch (e) { if (!controller.signal.aborted) { setError(message(e)); setReady(false); setExecutionAllowed(false); } }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 5000);
    }
    void poll(); return () => { controller.abort(); clearTimeout(timer); };
  }, [user.id, proposal?.id, refresh, restored, storedProposal]);
  async function restoreProposal(id: string) {
    await act('recover-proposal', async () => {
      const recovered = await api.recoverProposal(id);
      if (recovered.proposal.ownerId !== user.id) throw new Error('提案归属无法核对。');
      const value = recovered.proposal;
      rememberProposal(value); uncertainRevision.current = undefined;
      setProposal(value); setPlan(recovered.plan ?? undefined); setExecutionAllowed(false);
      setComparisonRef(undefined); setGoal(value.candidate.normalizedGoal); setSourceRef(value.input.sourceSnapshotRef); setApplicationId(value.candidate.application); setMode(value.candidate.mode);
      setChoices(value.input.materialChoices ?? {}); setConnectionRefs(value.input.connectionRefs ?? {});
      setRestored(true); setRefresh(n => n + 1);
    });
  }
  function selectApplication(id: string) {
    const selected = applications.find(item => item.id === id);
    setApplicationId(id); setMode(selected?.defaultMode ?? ''); setChoices({}); setConnectionRefs({});
  }
  function input(): CompositionInput {
    return { goal: goal.trim(), ...(sourceRef ? { sourceSnapshotRef: sourceRef } : {}), ...(application ? { application: application.id, applicationRef: { id: application.id, version: application.version, sha256: application.sha256 }, mode: mode || application.defaultMode } : {}), materialChoices: choices, connectionRefs };
  }
  async function createOrRevise() {
    if (!ready || comparisonStale || !goal.trim() || accepted || proposal && !uncertainRevision.current && (!pending || !proposal.allowedActions.includes('revise'))) return;
    const values = uncertainRevision.current?.input ?? input(); const parentId = uncertainRevision.current?.id ?? proposal?.id;
    await act(parentId ? 'revise-proposal' : 'propose', async () => {
      const key = await keys(parentId ? 'revise-proposal' : 'propose', { ...values, ...(parentId ? { parentId } : {}) });
      const alreadyUncertain = !!uncertainRevision.current;
      uncertainRevision.current ??= { id: parentId, input: values, requestId: key.requestId };
      let saved: AssemblyProposal;
      try {
        saved = parentId ? await api.reviseProposal(parentId, values, uncertainRevision.current.requestId) : await api.propose(values, uncertainRevision.current.requestId);
        if (saved.ownerId !== user.id || saved.input.goal !== values.goal || values.applicationRef && refKey(saved.candidate.applicationRef) !== refKey(values.applicationRef)
            || !sameSourceSnapshot(saved.input.sourceSnapshotRef, values.sourceSnapshotRef)) throw new Error('提案确认与原请求范围不一致；请核对原请求。');
      } catch (error) {
        if (!alreadyUncertain && error instanceof ApiError && error.status >= 400 && error.status < 500) uncertainRevision.current = undefined;
        throw error;
      }
      rememberProposal(saved); key.acknowledged(); uncertainRevision.current = undefined; setProposal(saved); setPlan(undefined); setExecutionAllowed(false);
      setApplicationId(saved.candidate.application); setMode(saved.candidate.mode);
      setChoices(saved.input.materialChoices ?? {}); setConnectionRefs(saved.input.connectionRefs ?? {});
    });
  }
  async function reject() {
    if (!ready || !proposal?.allowedActions.includes('reject')) return;
    await act('reject-proposal', async () => { const key = await keys('reject-proposal', { id: proposal.id, fingerprint: proposal.fingerprint }); const next = await api.rejectProposal(proposal.id, key.requestId); if (next.id !== proposal.id || next.state !== 'rejected') throw new Error('提案拒绝尚未确认。'); key.acknowledged(); setProposal(next); });
  }
  async function accept() {
    if (!ready || !proposal || !(proposal.allowedActions.includes('accept') || proposal.state === 'accepted' && !plan)) return;
    await act('accept-proposal', async () => {
      const key = await keys('accept-proposal', { id: proposal.id, fingerprint: proposal.fingerprint });
      const next = await api.acceptProposal(proposal.id, key.requestId);
      if (!sameSourceSnapshot(next.sourceSnapshotRef, proposal.candidate.sourceSnapshotRef) || !next.applicationRef || refKey(next.applicationRef) !== refKey(proposal.candidate.applicationRef) || next.normalizedGoal !== proposal.candidate.normalizedGoal
          || next.materialRefs.length !== proposal.candidate.materialRefs.length || next.materialRefs.some((ref, i) => refKey(ref) !== refKey(proposal.candidate.materialRefs[i]))) throw new Error('最终方案与提案固定范围不一致；请核对原请求。');
      // Keep this key: an uncertain acceptance retry must recover the same immutable plan.
      setPlan(next); setExecutionAllowed(false); setRefresh(n => n + 1);
    });
  }
  async function instantiate() {
    if (!ready || !plan || plan.status !== 'ready' || !executionAllowed || !bindingsCurrent || plan.usageBudget !== undefined && !usageCommitment(plan.usageBudget)) return;
    await act('instantiate', async () => { const key = await keys('instantiate', { planId: plan.id, executionTargetRef: target || null }); try { const job = await api.instantiate(plan.id, key.requestId, target || undefined); onCreated(job.id); } catch (e) { setRefresh(n => n + 1); throw e; } });
  }
  function startAgain() { setComparisonRef(undefined); rememberProposal(); setRestored(true); setProposal(undefined); setPlan(undefined); setExecutionAllowed(false); setGoal(''); setSourceRef(undefined); setChoices({}); setConnectionRefs({}); uncertainRevision.current = undefined; }
  const candidate = proposal?.candidate;
  const usageVerified = plan?.usageBudget === undefined || !!usageCommitment(plan.usageBudget);
  const bound = plan?.bindingManifest?.connections;
  const bindingsCurrent = !bound || typeof bound === 'object' && Object.values(bound).every(pin => pin && typeof pin === 'object' && typeof pin.ref === 'string' && connections.some(item => item.ref === pin.ref && item.available && item.fingerprint === pin.fingerprint));
  const choiceSignature = (value: Record<string, MaterialReference>) => Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([slot, ref]) => `${slot}:${refKey(ref)}`).join('|');
  const connectionSignature = (value: Record<string, string>) => Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([slot, ref]) => `${slot}:${ref}`).join('|');
  const dirty = !!candidate && (!sameSourceSnapshot(sourceRef, candidate.sourceSnapshotRef) || goal.trim() !== candidate.normalizedGoal || application && refKey(application) !== refKey(candidate.applicationRef) || mode && mode !== candidate.mode
    || choiceSignature(choices) !== choiceSignature(proposal?.input.materialChoices ?? {}) || connectionSignature(connectionRefs) !== connectionSignature(proposal?.input.connectionRefs ?? {}));
  return <><CompositionInbox ownerId={user.id} loadPage={api.proposalInbox} onSelect={id => void restoreProposal(id)} disabled={!!busy} refreshKey={`${proposal?.id ?? ''}:${proposal?.state ?? ''}`}/><section className="composer" aria-labelledby="composer-title"><div className="section-heading"><h2 id="composer-title">新的应用任务</h2><span className="quiet">有边界的装配</span></div>{error && <div role="alert" className="error-message">{error}<button className="text-button" onClick={() => setRefresh(n => n + 1)}>重新核对装配</button></div>}
    {!ready && storedProposal && !restored && <button className="secondary" disabled={!!busy} onClick={startAgain}>保留原记录并开始新的装配</button>}
    {comparisonRef && <p className="state-note">此方案固定已选比较应用版本。合成开发数据仅用于验证工作流；数据、评估器和候选范围由已发布材料固定。{comparisonStale && ' 当前应用版本不可用，请返回比较目录重新核对。'}</p>}
    {sourceRef && <div className="state-note source-plan-note"><p>已固定来源快照。问题须与快照一致；请选择已批准的受控综合应用和自己的模型连接。</p><span>快照 {sourceRef.id}</span><span>指纹 {sourceRef.fingerprint}</span><p>下一步仍需生成提案、固定方案并完成独立审查。来源变化会阻止执行；受控产物不是科学结论。</p></div>}
    {uncertainRevision.current && <p className="policy-note">原装配请求未确认，输入已锁定。重试保持同一请求；刷新后请从提案历史核对原记录。</p>}
    <form onSubmit={event => { event.preventDefault(); void createOrRevise(); }}><label htmlFor="application-selector">已批准的应用</label><select id="application-selector" value={applicationId} disabled={!!comparisonRef || !!busy || !!uncertainRevision.current || accepted || !ready || !!proposal && !pending} onChange={event => selectApplication(event.target.value)}><option value="">根据目标从已批准应用中选择</option>{applications.map(item => <option key={refKey(item)} value={item.id}>{item.name} · v{item.version}</option>)}</select>{application && <p className="quiet">{application.description}</p>}<label htmlFor="research-topic">任务目标</label><textarea id="research-topic" rows={4} value={goal} disabled={!!comparisonRef || !!sourceRef || !!busy || !!uncertainRevision.current || accepted || !!proposal && !pending} onChange={event => setGoal(event.target.value)} placeholder="描述想调查的问题、比较范围或需要计算验证的结果。" required maxLength={2000}/>
      {application && <label>执行方式<select aria-label="应用执行方式" value={mode || application.defaultMode} disabled={!!comparisonRef || !!busy || !!uncertainRevision.current || accepted || !!proposal && !pending} onChange={event => { setMode(event.target.value); setChoices({}); setConnectionRefs({}); }}>{Object.keys(application.modes).map(value => <option key={value} value={value}>{modeName(value)}</option>)}</select></label>}
      {selectedMode && Object.entries(selectedMode.materialChoices).map(([slot, choice]) => <label key={slot}>{kindNames[choice.kind]}选择 · {slot}<select aria-label={`材料选择 ${slot}`} disabled={!!busy || !!uncertainRevision.current || accepted || !!proposal && !pending || !ready} value={refKey(choices[slot] ?? choice.defaultRef)} onChange={event => { const ref = choice.allowedRefs.find(item => refKey(item) === event.target.value); if (ref) setChoices(current => ({ ...current, [slot]: ref })); }}>{choice.allowedRefs.map(ref => <option key={refKey(ref)} value={refKey(ref)}>{materials.find(item => refKey(item) === refKey(ref))?.name ?? ref.id} · v{ref.version}</option>)}</select></label>)}
      {selectedMode?.connectionRequirements.map(requirement => <label key={requirement.name}>资源连接 · {requirement.name}{requirement.required ? '（必需）' : '（可选）'}<select aria-label={`资源连接 ${requirement.name}`} value={connectionRefs[requirement.name] ?? ''} disabled={!!busy || !!uncertainRevision.current || accepted || !!proposal && !pending || !ready} onChange={event => setConnectionRefs(current => { const next = { ...current }; if (event.target.value) next[requirement.name] = event.target.value; else delete next[requirement.name]; return next; })}><option value="">未选择连接</option>{connections.filter(item => item.available && !item.taskId && item.kind === requirement.kind && requirement.requiredCapabilities.every(capability => item.capabilities.includes(capability))).map(item => <option key={item.ref} value={item.ref}>{item.registrationRef} · {item.ref.slice(0, 8)}</option>)}</select><small className="quiet">只可选自己的可用用户范围引用；配置可用不等于真实提供商已验证。</small></label>)}
      {!accepted && (!proposal || pending || uncertainRevision.current) && <button className="primary wide" type="submit" disabled={comparisonStale || !!busy || !ready || !goal.trim() || !!proposal && !uncertainRevision.current && !proposal.allowedActions.includes('revise')}>{busy === 'propose' || busy === 'revise-proposal' ? '正在装配…' : uncertainRevision.current ? '核对原装配请求' : proposal ? '按当前选择修订提案' : '生成装配提案'}</button>}
    </form>
    {candidate && <div className="preflight"><div className="section-heading"><h3>装配提案</h3><span className={`badge ${candidate.status === 'ready' ? 'status-ready' : 'status-blocked'}`}>{candidate.status === 'ready' ? '预检通过' : '预检存在缺项'}</span></div><p className="normalized-goal">{candidate.normalizedGoal}</p><p className="quiet">应用 {applications.find(item => item.id === candidate.application)?.name ?? candidate.application} · v{candidate.applicationRef.version} · {modeName(candidate.mode)} · {({ pending: '等待你的决定', revised: '已被新提案修订', rejected: '已拒绝', accepted: '已固定为方案' })[proposal!.state]}</p>
      {candidate.syntheticFixture && <div className="state-note">合成演示适配器：装配与生命周期可验证，文献和实验结果不能作为真实研究证据；不会调用付费模型。</div>}
      <dl className="plan-details"><dt>六类固定材料</dt><dd>{Object.entries(kindNames).map(([kind, name]) => <div className="application-material-group" key={kind}><strong>{name}</strong>{candidate.materialRefs.filter(ref => candidate.materials.find(item => refKey(item) === refKey(ref))?.kind === kind).map(ref => <span className="material-chip" key={refKey(ref)}>{candidate.materials.find(item => refKey(item) === refKey(ref))?.name ?? ref.id} <small>v{ref.version}</small></span>)}{!candidate.materials.some(item => item.kind === kind) && <span className="quiet">此方式未选择</span>}</div>)}</dd><dt>注册适配器</dt><dd>{adapterNames(candidate.executionBindings).map(name => <span className="material-chip" key={name}>{name}</span>)}{!candidate.executionBindings && '绑定尚未通过预检'}</dd><dt>工具</dt><dd>{candidate.tools.join('、') || '无工具'}</dd><dt>能力边界</dt><dd>{candidate.capabilities.join('、')}</dd><dt>固定配置</dt><dd><pre className="reviewed-configuration">{JSON.stringify(candidate.config, null, 2)}</pre></dd><dt>固定预算</dt><dd>{Object.entries(candidate.budget).map(([key, value]) => <span className="material-chip" key={key}>{budgetNames[key] ?? key} {value}</span>)}</dd></dl>
      {candidate.missing.length > 0 && <ul className="missing-list">{candidate.missing.map((item, i) => <li key={i}>{item}</li>)}</ul>}
      <details className="technical-detail"><summary>准确版本、适配器与绑定依据</summary><span>提案 {proposal!.id}</span><span>指纹 {proposal!.fingerprint}</span><span>应用 {refKey(candidate.applicationRef)}</span><span>选择依据 {proposal!.selection.method} · {proposal!.selection.matchedKeywords.join('、') || '明确选择'}</span><pre>{JSON.stringify({ materialRefs: candidate.materialRefs, executionBindings: candidate.executionBindings, bindingManifest: candidate.bindingManifest }, null, 2)}</pre></details>
      {!accepted && pending && dirty && <p className="policy-note">当前修改尚未生成新提案；请先按当前选择修订，再接受新提案。</p>}
      {!accepted && pending && <div className="button-row"><button className="primary" disabled={!!busy || !ready || dirty || !proposal!.allowedActions.includes('accept')} onClick={() => void accept()}>{busy === 'accept-proposal' ? '等待方案确认…' : '接受提案并固定方案'}</button><button className="secondary danger" disabled={!!busy || !ready || !proposal!.allowedActions.includes('reject')} onClick={() => void reject()}>拒绝此提案</button></div>}
      <p className="policy-note">接受只固定方案，不会开始执行。修改会生成新的提案并保留原记录。能力、预算和适配器范围由已批准定义与后端检查决定。</p>
    </div>}
    {proposal?.state === 'accepted' && !plan && <div className="state-note"><p>服务端已接受此提案，但本页尚未收到最终方案。可只读找回原方案。</p><button className="secondary" disabled={!!busy || !ready} onClick={() => void restoreProposal(proposal.id)}>读取原方案</button></div>}
    {plan && <div className="preflight"><h3>已固定的执行方案</h3><p>方案已保存，材料和绑定范围不可修改。{plan.status === 'blocked' ? '预检缺项仍阻止创建任务。' : '通过当前授权检查后可创建临时实例。'}</p><UsageCommitmentSummary value={plan.usageBudget}/><PlanReviewGate key={plan.id} ownerId={user.id} plan={plan} busy={busy} act={act} onAllowed={setExecutionAllowed}/>{!bindingsCurrent && <p role="status" className="policy-note">方案中的连接当前不可用或已变更；请重新装配。后端在执行前仍会重新检查绑定。</p>}{targets.length > 0 && <label>执行位置<select aria-label="执行位置" value={target} disabled={!!busy} onChange={event => setTarget(event.target.value)}><option value="">当前 Factory</option>{targets.map(item => <option key={item.id} value={item.id}>{item.name} · 远程 Factory</option>)}</select></label>}<button className="primary wide" disabled={!!busy || !ready || plan.status !== 'ready' || !executionAllowed || !bindingsCurrent || !usageVerified} onClick={() => void instantiate()}>{busy === 'instantiate' ? '等待实例确认…' : '确认方案并创建任务'}</button>{user.role === 'manager' && onSchedule && <button className="secondary wide" disabled={!!busy || plan.status !== 'ready' || !executionAllowed || !bindingsCurrent || !usageVerified || !!target} onClick={() => onSchedule(plan)}>用此已批准方案设置计划任务</button>}<details className="technical-detail"><summary>最终方案凭据</summary><span>方案 {plan.id}</span><span>指纹 {plan.fingerprint}</span></details></div>}
    {proposal && (!pending || accepted) && <button className="secondary wide" disabled={!!busy} onClick={startAgain}>开始新的装配</button>}
  </section></>;
}
