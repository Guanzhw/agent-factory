import { useState } from 'react';
import type { ResearchAgreement } from './types.js';

export function AgreementEditor({ initial, disabled, onSave }: { initial?: ResearchAgreement; disabled: boolean; onSave: (agreement: ResearchAgreement) => void }) {
  const [objective, setObjective] = useState(initial?.objective ?? '');
  const [evaluation, setEvaluation] = useState(initial?.evaluation ?? '');
  const [stopConditions, setStopConditions] = useState(initial?.stopConditions ?? '');
  const [rounds, setRounds] = useState(initial ? String(initial.budget.rounds) : '');
  const [toolCalls, setToolCalls] = useState(initial ? String(initial.budget.toolCalls) : '');
  const [metered, setMetered] = useState(initial?.budget.tokenLimit != null);
  const [tokens, setTokens] = useState(initial?.budget.tokenLimit?.toString() ?? '');
  const [amount, setAmount] = useState(initial?.budget.amountMicros == null ? '' : String(initial.budget.amountMicros / 1_000_000));
  const [currency, setCurrency] = useState<'USD' | 'EUR' | 'CNY'>(initial?.budget.currency ?? 'CNY');
  const [resources, setResources] = useState(Object.entries(initial?.resourceRefs ?? {}).map(([slot, ref]) => ({ slot, ref })));
  const [error, setError] = useState('');
  return <form className="material-editor" aria-label="研究约定" onSubmit={event => {
    event.preventDefault(); setError('');
    const slots = resources.map(item => item.slot.trim());
    if (new Set(slots).size !== slots.length) { setError('资源用途不能重复。'); return; }
    onSave({ objective: objective.trim(), evaluation: evaluation.trim(), stopConditions: stopConditions.trim(), resourceRefs: Object.fromEntries(resources.map(item => [item.slot.trim(), item.ref.trim()])), budget: {
      rounds: Number(rounds), toolCalls: Number(toolCalls), tokenLimit: metered ? Number(tokens) : null,
      amountMicros: metered ? Math.round(Number(amount) * 1_000_000) : null, currency: metered ? currency : null,
    } });
  }}><h2>{initial ? '修订研究约定' : '建立研究约定'}</h2><p>明确目标和边界，保存后单独确认。保存资源引用不会启动任务或验证资源可用性。</p>
    <fieldset disabled={disabled}>
      <label>研究目标<textarea required maxLength={4000} value={objective} onChange={event => setObjective(event.target.value)}/></label>
      <label>评价与达标标准<textarea required maxLength={4000} value={evaluation} onChange={event => setEvaluation(event.target.value)}/></label>
      <label>停止与放弃条件<textarea required maxLength={4000} value={stopConditions} onChange={event => setStopConditions(event.target.value)}/></label>
      <div className="editor-grid"><label>最多实验轮数<input type="number" required min="1" step="1" value={rounds} onChange={event => setRounds(event.target.value)}/></label><label>最多工具调用<input type="number" required min="1" step="1" value={toolCalls} onChange={event => setToolCalls(event.target.value)}/></label></div>
      <label><input type="checkbox" checked={metered} onChange={event => setMetered(event.target.checked)}/>记录模型用量与金额上限</label>
      {metered && <div className="editor-grid"><label>Token 上限<input type="number" required min="0" step="1" value={tokens} onChange={event => setTokens(event.target.value)}/></label><label>金额上限<input type="number" required min="0" step="0.000001" value={amount} onChange={event => setAmount(event.target.value)}/></label><label>币种<select value={currency} onChange={event => setCurrency(event.target.value as typeof currency)}><option value="CNY">CNY</option><option value="USD">USD</option><option value="EUR">EUR</option></select></label></div>}
      <h3>已保存资源</h3><p>仅填写资源中心中的引用，不填写密码、密钥或连接秘密。</p>
      {resources.map((item, index) => <div className="editor-grid" key={index}><label>资源用途<input required maxLength={200} pattern="[A-Za-z0-9_.:-]+" value={item.slot} onChange={event => setResources(values => values.map((value, i) => i === index ? { ...value, slot: event.target.value } : value))}/></label><label>资源引用<input required maxLength={200} pattern="[A-Za-z0-9_.:-]+" value={item.ref} onChange={event => setResources(values => values.map((value, i) => i === index ? { ...value, ref: event.target.value } : value))}/></label><button type="button" onClick={() => setResources(values => values.filter((_, i) => i !== index))}>移除资源引用</button></div>)}
      <button type="button" className="secondary" disabled={resources.length >= 30} onClick={() => setResources(values => [...values, { slot: '', ref: '' }])}>添加资源引用</button>
      {error && <p role="alert">{error}</p>}<button type="submit" className="primary">保存研究约定</button>
    </fieldset>
  </form>;
}
