import { useId, useState } from 'react';
import { kindNames, type FactoryMaterial, type MaterialReference } from './models.js';
import { catalogMaterials, exactMaterialKey, materialKinds, materialReference, runtimeBindingSummary, selectionIssues, toggleMaterialSelection } from './materialCatalogState.js';

export interface MaterialPickerProps {
  materials: FactoryMaterial[];
  selected: MaterialReference[];
  onChange: (refs: MaterialReference[]) => void;
  disabled?: boolean;
  kind?: FactoryMaterial['kind'];
  label: string;
}

export function MaterialPicker({ materials, selected, onChange, disabled = false, kind, label }: MaterialPickerProps) {
  const id = useId();
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<FactoryMaterial['kind'] | ''>('');
  const visible = catalogMaterials(materials, query, kind ?? (filter || undefined));
  const selectedKeys = new Set(selected.map(exactMaterialKey));
  const issues = selectionIssues(materials, selected);
  return <fieldset className="material-picker" disabled={disabled}>
    <legend>{label}</legend>
    <p id={`${id}-help`} className="quiet">选择固定版本。依赖、权限与运行绑定由服务端预检；这里不会自动添加或替换素材。</p>
    <div className="material-picker-filters">
      <label htmlFor={`${id}-search`}>搜索素材名称、编号或说明</label>
      <input id={`${id}-search`} type="search" value={query} onChange={event => setQuery(event.target.value)} aria-describedby={`${id}-help`} />
      {!kind && <label>素材类型<select value={filter} onChange={event => setFilter(event.target.value as FactoryMaterial['kind'] | '')}>
        <option value="">全部类型</option>{materialKinds.map(item => <option key={item} value={item}>{kindNames[item]}</option>)}
      </select></label>}
    </div>
    <p role="status" className="quiet">可选 {visible.length} 项 · 已选 {selected.length} 项</p>
    {selected.length > 0 && <section aria-label={`${label}已选项`} className="material-picker-selected">
      <h4>已选固定版本</h4>
      <ul>{issues.map(({ ref, material, unavailable, missingDependencies }, index) => <li key={`${exactMaterialKey(ref)}:${index}`}>
        <span>{material?.name ?? ref.id} · {ref.id} v{ref.version}</span>
        {unavailable && <strong className="state-note"> 此精确版本已撤回、归档或不在当前目录中，请移除或另选。</strong>}
        {missingDependencies.length > 0 && <p className="state-note">尚未选入依赖：{missingDependencies.map(dep => `${dep.id} v${dep.version} (${dep.sha256})`).join('；')}。不会自动补齐。</p>}
        <details><summary>固定内容摘要</summary><code style={{ overflowWrap: 'anywhere' }}>{ref.sha256}</code></details>
        <button type="button" className="secondary" aria-label={`移除 ${ref.id} 版本 ${ref.version} 摘要 ${ref.sha256}`} onClick={() => onChange(selected.filter((_, position) => position !== index).map(materialReference))}>移除此选择</button>
      </li>)}</ul>
    </section>}
    {visible.length === 0 && <p className="list-empty">没有匹配的已批准素材。可以调整搜索或筛选；已选版本会继续保留。</p>}
    {materialKinds.map(group => {
      const entries = visible.filter(material => material.kind === group);
      return entries.length > 0 && <fieldset key={group} className="material-picker-group"><legend>{kindNames[group]}</legend>
        {entries.map(material => <article key={exactMaterialKey(material)} className="material-picker-card">
          <label><input type="checkbox" checked={selectedKeys.has(exactMaterialKey(material))} onChange={event => onChange(toggleMaterialSelection(selected, material, event.target.checked))} />
            <strong>{material.name}</strong> · {material.id} v{material.version}</label>
          <p>{material.description}</p>
          <dl className="plan-details"><dt>许可证</dt><dd>{material.license || '未提供'}</dd>
            <dt>固定依赖</dt><dd>{material.dependencies.length ? material.dependencies.map(ref => `${ref.id} v${ref.version}`).join('、') : '无'}</dd>
            <dt>注册运行绑定</dt><dd>{runtimeBindingSummary(material)}</dd>
          </dl>
          <details><summary>版本摘要与兼容性</summary><code style={{ overflowWrap: 'anywhere' }}>{material.sha256}</code><p>{material.compatibility.join('、') || '未声明兼容性'}</p></details>
        </article>)}
      </fieldset>;
    })}
  </fieldset>;
}
