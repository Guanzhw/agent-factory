import { useState } from 'react';
import { applicationInputSchema } from './applicationInputState.js';
import { MaterialPicker } from './MaterialPicker.js';
import { budgetBounds, configBounds, inspectTemplate, updateTemplate, type TemplateChange } from './applicationTemplateState.js';
import { kindNames, type ApplicationMode, type FactoryMaterial, type MaterialReference } from './models.js';

export interface ApplicationTemplateEditorProps {
  definition: Record<string, unknown>;
  materials: FactoryMaterial[];
  onChange: (next: Record<string, unknown>) => void;
  disabled?: boolean;
}
const budgetNames: Record<string, string> = { toolCalls: '工具调用次数', maxDepth: '委派深度', maxChildren: '累计子任务数', experimentSeconds: '实验时长（秒）', outputBytes: '产物大小（字节）' };
const configNames: Record<string, string> = { experimentDurationSeconds: '单次实验时长（秒）', askScopeBelowLength: '目标少于多少字符时询问范围' };
const reference = (ref: MaterialReference) => `${ref.id}@${ref.version}:${ref.sha256}`;
function InputSchemaEditor({ value, disabled, onChange }: { value: unknown; disabled: boolean; onChange: (value: unknown) => void }) {
  const [text, setText] = useState(value === undefined ? '' : JSON.stringify(value, null, 2));
  const [error, setError] = useState('');
  return <details><summary>高级：可选应用输入定义</summary><p>使用有界 JSON 对象定义任务输入字段。字符串和数组必须限制长度；只支持内联字段，不支持引用或执行逻辑。</p>
    <label>输入定义 JSON<textarea aria-label="输入定义 JSON" value={text} rows={8} maxLength={32768} disabled={disabled} onChange={event => { setText(event.target.value); setError(''); }}/></label>
    <button type="button" className="secondary" disabled={disabled} onClick={() => { try { const next = text.trim() ? applicationInputSchema(JSON.parse(text)) : undefined; onChange(next); setError(''); } catch { setError('输入定义无效，请核对有界字段结构。'); } }}>应用输入定义</button>
    <p className="quiet">留空并应用会移除本方式的自定义输入。此修改仍需独立审查发布。</p>{error && <p role="alert">{error}</p>}
  </details>;
}
export function ApplicationTemplateEditor({ definition, materials, onChange, disabled = false }: ApplicationTemplateEditorProps) {
  const inspection = inspectTemplate(definition, materials);
  const [selectedMode, setSelectedMode] = useState('');
  const [changeError, setChangeError] = useState('');
  const mode = inspection.modes.find(item => item.name === selectedMode) ?? inspection.modes[0];
  const modeDefinition = mode ? (definition.modes as Record<string, ApplicationMode>)[mode.name] : undefined;
  function change(value: TemplateChange) {
    if (disabled || !inspection.guided) return;
    try { const next = updateTemplate(definition, value, materials); onChange(next); setChangeError(''); }
    catch (error) { setChangeError(error instanceof Error ? error.message : '无法修改此模板，请核对高级定义。'); }
  }
  const keywords = Array.isArray(definition.discoveryKeywords) ? definition.discoveryKeywords as string[] : [];
  const toolOrder = modeDefinition?.toolOrder ?? [];
  function moveTool(index: number, offset: number) {
    if (!mode || index + offset < 0 || index + offset >= toolOrder.length) return;
    const next = [...toolOrder]; [next[index], next[index + offset]] = [next[index + offset], next[index]];
    change({ kind: 'toolOrder', mode: mode.name, tools: next });
  }
  return <section className="application-template-editor" aria-label="应用模板编辑">
    <h2>编辑应用模板</h2><p>从已载入的模板调整名称、固定材料和执行预算。这里只修改作者草稿；保存后仍需另一位管理员审查发布，之后才能供任务装配。</p>
    {inspection.errors.length > 0 && <div className="error-message" role="alert"><div><strong>草稿需要核对</strong><ul>{inspection.errors.map((error, index) => <li key={index}>{error}</li>)}</ul></div></div>}
    {inspection.warnings.length > 0 && <div className="policy-note"><ul>{inspection.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></div>}
    {changeError && <p className="error-message" role="alert">{changeError}</p>}
    {!inspection.guided ? <p className="state-note">此定义含尚不支持的结构或扩展字段，请使用高级 JSON 编辑。原定义保持不变，不会自动删减材料、连接或能力范围。</p> : <>
      <fieldset disabled={disabled}><legend>用户如何找到这个应用</legend>
        <label>应用名称<input aria-label="应用名称" value={String(definition.name ?? '')} onChange={event => change({ kind: 'metadata', field: 'name', value: event.target.value })}/></label>
        <label>应用说明<textarea aria-label="应用说明" rows={3} value={String(definition.description ?? '')} onChange={event => change({ kind: 'metadata', field: 'description', value: event.target.value })}/></label>
        <p className="quiet">发现关键词用于从用户目标中匹配应用，不会增加执行权限。</p>
        {keywords.map((keyword, index) => <div className="button-row" key={index}><label>发现关键词 {index + 1}<input aria-label={`发现关键词 ${index + 1}`} value={keyword} onChange={event => change({ kind: 'metadata', field: 'discoveryKeywords', value: keywords.map((value, i) => i === index ? event.target.value : value) })}/></label><button type="button" className="text-button" aria-label={`删除发现关键词 ${index + 1}`} onClick={() => change({ kind: 'metadata', field: 'discoveryKeywords', value: keywords.filter((_, i) => i !== index) })}>删除</button></div>)}
        <button type="button" className="secondary" onClick={() => change({ kind: 'metadata', field: 'discoveryKeywords', value: [...keywords, ''] })}>添加发现关键词</button>
        <label>默认执行方式<select aria-label="默认执行方式" value={String(definition.defaultMode ?? '')} onChange={event => change({ kind: 'metadata', field: 'defaultMode', value: event.target.value })}>{inspection.modes.map(item => <option key={item.name} value={item.name}>{item.name}</option>)}</select></label>
        <label><input type="checkbox" checked={definition.defaultForDiscovery === true} onChange={event => change({ kind: 'metadata', field: 'defaultForDiscovery', value: event.target.checked })}/>作为默认发现候选</label>
      </fieldset>
      {mode && modeDefinition && <fieldset disabled={disabled}><legend>这项任务可以做什么</legend>
        <InputSchemaEditor key={`${mode.name}:${JSON.stringify(modeDefinition.inputSchema)}`} value={modeDefinition.inputSchema} disabled={disabled} onChange={value => change({ kind: 'inputSchema', mode: mode.name, value })}/>
        <label>编辑执行方式<select aria-label="编辑执行方式" value={mode.name} onChange={event => { setSelectedMode(event.target.value); setChangeError(''); }}>{inspection.modes.map(item => <option key={item.name} value={item.name}>{item.name}</option>)}</select></label>
        <MaterialPicker label="固定材料" materials={materials} selected={modeDefinition.materialRefs} disabled={disabled} onChange={refs => change({ kind: 'modeRefs', mode: mode.name, refs })}/>
        <p className="quiet">选择固定版本，不自动添加依赖或扩大能力。材料缺失、版本变更和依赖问题需要先解决；最终由服务端检查发布条件。</p>
        {mode.slots.map(slot => <label key={slot.name}>默认材料 {slot.name} · {kindNames[slot.kind]}<select aria-label={`默认材料 ${slot.name}`} value={reference(slot.defaultRef)} onChange={event => { const ref = slot.allowedRefs.find(item => reference(item) === event.target.value); if (ref) change({ kind: 'slotDefault', mode: mode.name, slot: slot.name, ref }); }}>{slot.allowedRefs.map(ref => <option key={reference(ref)} value={reference(ref)}>{materials.find(item => reference(item) === reference(ref))?.name ?? ref.id} · v{ref.version}</option>)}</select><small className="quiet">仅可选择原模板已定义的候选范围。</small></label>)}
        <h3>任务预算</h3><p className="quiet">预算限定一次任务的工作量，不代表底层机器已提供相应隔离或配额。</p>
        {Object.entries(budgetBounds).map(([field, bounds]) => <label key={field}>{budgetNames[field] ?? field}<input type="number" aria-label={`预算 ${budgetNames[field] ?? field}`} min={bounds[0]} max={bounds[1]} step={1} value={modeDefinition.budget[field as keyof typeof modeDefinition.budget] ?? ''} onChange={event => change({ kind: 'budget', mode: mode.name, field, value: Number(event.target.value) })}/><small className="quiet">允许范围 {bounds[0]}–{bounds[1]}</small></label>)}
        {Object.entries(configBounds).filter(([field]) => Object.hasOwn(modeDefinition.config, field)).map(([field, bounds]) => <label key={field}>{configNames[field] ?? field}<input type="number" aria-label={`配置 ${configNames[field] ?? field}`} min={bounds[0]} max={bounds[1]} step={1} value={Number(modeDefinition.config[field])} onChange={event => change({ kind: 'config', mode: mode.name, field, value: Number(event.target.value) })}/></label>)}
        <h3>工具执行顺序</h3><p className="quiet">调整现有工具的顺序，不添加工具或扩大权限。</p>
        {toolOrder.length ? <ol>{toolOrder.map((tool, index) => <li key={tool}><span>{tool}</span><button type="button" className="text-button" aria-label={`上移工具 ${tool}`} disabled={disabled || index === 0} onClick={() => moveTool(index, -1)}>上移</button><button type="button" className="text-button" aria-label={`下移工具 ${tool}`} disabled={disabled || index === toolOrder.length - 1} onClick={() => moveTool(index, 1)}>下移</button></li>)}</ol> : <p>沿用服务端根据材料确定的默认顺序。</p>}
        {!toolOrder.length && mode.toolNames.length > 0 && <button type="button" className="secondary" onClick={() => change({ kind: 'toolOrder', mode: mode.name, tools: mode.toolNames })}>载入当前工具顺序以调整</button>}
        {toolOrder.length > 0 && <button type="button" className="text-button" onClick={() => change({ kind: 'toolOrder', mode: mode.name, tools: [] })}>恢复服务端默认工具顺序</button>}
        <details className="technical-detail"><summary>保留的能力、连接与准确版本</summary><p>可视化编辑不修改这些高级范围；如需调整，请使用高级 JSON 并重新提交发布审查。</p><pre>{JSON.stringify({ capabilities: modeDefinition.capabilities, connectionRequirements: modeDefinition.connectionRequirements, materialRefs: modeDefinition.materialRefs, materialChoices: modeDefinition.materialChoices, config: modeDefinition.config }, null, 2)}</pre></details>
      </fieldset>}
    </>}
  </section>;
}
