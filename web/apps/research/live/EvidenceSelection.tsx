import { useEffect, useState } from 'react';
import type { ResearchAgreement } from '../types.js';
import { setupApi, type SetupCandidates } from './setupClient.js';
const roles = { metrics: '指标', source: '源码', run_recipe: '运行配方' };
export function EvidenceSelection({ ownerId, value, onChange, onMaterials }: { ownerId: string; value: NonNullable<ResearchAgreement['evidence']> | null; onChange: (value: NonNullable<ResearchAgreement['evidence']> | null) => void; onMaterials: () => void }) {
  const [materials, setMaterials] = useState<SetupCandidates['experimentMaterials'] | null>(null);
  const [error, setError] = useState(''); const [load, setLoad] = useState(0);
  useEffect(() => {
    if (!load) return;
    const controller = new AbortController(); setMaterials(null); setError('');
    void setupApi.candidates(ownerId, controller.signal).then(result => { if (!controller.signal.aborted) setMaterials(result.experimentMaterials); }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '无法读取材料'); });
    return () => controller.abort();
  }, [ownerId, load]);
  const key = (pin: { id: string; version: number; sha256: string }) => `${pin.id}:${pin.version}:${pin.sha256}`;
  return <section aria-label="精选证据设置"><h3>精选证据公开范围</h3><p>只公开已确认CLI原输出的选中顶层字段，不公开整个输出、私聊或连接。材料必须与实际唯一CLI工具精确匹配，由服务端核对。</p>
    <button type="button" onClick={() => setLoad(count => count + 1)}>读取已发布实验材料</button><button type="button" onClick={onMaterials}>管理材料</button>{error && <p role="alert">{error}</p>}
    {value && <p className="rw-id">原选择：{value.toolMaterial.id} v{value.toolMaterial.version} · {value.toolMaterial.sha256}</p>}
    {materials && <label>证据CLI材料<select value={value ? key(value.toolMaterial) : ''} onChange={event => { const selected = materials.find(item => key(item) === event.target.value); onChange(selected ? { toolMaterial: { id: selected.id, version: selected.version, sha256: selected.sha256 }, fields: value?.fields ?? {} } : null); }}><option value="">未配置精选证据</option>{value && !materials.some(item => key(item) === key(value.toolMaterial)) && <option value={key(value.toolMaterial)}>保留原精准版本（当前目录不可用）</option>}{materials.map(item => <option key={key(item)} value={key(item)} disabled={!item.available}>{item.name} · v{item.version}{!item.available ? ' · 不可用' : ''}</option>)}</select></label>}
    {materials?.length === 0 && <p>没有可用的已发布实验材料，请先管理材料与资源；不会补造默认证据。</p>}
    {value ? <>{Object.entries(roles).map(([role, label]) => <label key={role}>{label}输出字段<input maxLength={100} pattern="[A-Za-z_][A-Za-z0-9_]*" placeholder="留空表示不公开此角色" value={value.fields[role as keyof typeof roles] ?? ''} onChange={event => { const fields = { ...value.fields }; if (event.target.value) fields[role as keyof typeof roles] = event.target.value; else delete fields[role as keyof typeof roles]; onChange({ ...value, fields }); }}/></label>)}<p>至少选择一个字段；缺源码或配方会如实标为成果不完整。配方需要命令、依赖、数据前提和预期结果。</p><button type="button" onClick={() => onChange(null)}>明确移除精选证据选择</button></> : <p>尚未配置精选证据，不能据此获得可复现成果。</p>}
  </section>;
}
