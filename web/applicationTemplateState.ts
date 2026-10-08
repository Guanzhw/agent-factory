import type { FactoryApplication, FactoryMaterial, MaterialReference } from './models.js';

export const budgetBounds: Record<string, readonly [number, number]> = {
  toolCalls: [1, 128], maxDepth: [1, 8], maxChildren: [1, 64], experimentSeconds: [1, 600], outputBytes: [1024, 1048576],
};
export const configBounds: Record<string, readonly [number, number]> = {
  askScopeBelowLength: [0, 2000], experimentDurationSeconds: [1, 600],
};
export type TemplateChange =
  | { kind: 'metadata'; field: 'name' | 'description' | 'discoveryKeywords' | 'defaultMode' | 'defaultForDiscovery'; value: unknown }
  | { kind: 'modeRefs'; mode: string; refs: MaterialReference[] }
  | { kind: 'slotDefault'; mode: string; slot: string; ref: MaterialReference }
  | { kind: 'budget' | 'config'; mode: string; field: string; value: number }
  | { kind: 'toolOrder'; mode: string; tools: string[] };
export interface TemplateModeView {
  name: string;
  materials: { ref: MaterialReference; material: FactoryMaterial | null }[];
  toolNames: string[];
  slots: { name: string; kind: FactoryMaterial['kind']; defaultRef: MaterialReference; allowedRefs: MaterialReference[] }[];
}
export interface TemplateInspection { guided: boolean; errors: string[]; warnings: string[]; modes: TemplateModeView[] }
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const identifier = (v: unknown): v is string => typeof v === 'string' && /^[A-Za-z0-9_.:-]{1,100}$/.test(v);
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(x => typeof x === 'string');
const kinds = ['skill', 'tool', 'prompt', 'knowledge', 'model', 'environment'];
export const templateRefKey = (r: MaterialReference) => `${r.id}@${r.version}:${r.sha256}`;
const pin = (v: unknown): v is MaterialReference => record(v) && Object.keys(v).length === 3
  && identifier(v.id) && Number.isSafeInteger(v.version) && Number(v.version) > 0
  && typeof v.sha256 === 'string' && /^[a-f0-9]{64}$/.test(v.sha256);
const pins = (v: unknown): v is MaterialReference[] => Array.isArray(v) && v.every(pin);
const same = (a: MaterialReference, b: MaterialReference) => templateRefKey(a) === templateRefKey(b);
const available = (m: FactoryMaterial) => m.published === true && !m.archived
  && (!m.governance || m.governance.state === 'published');
const find = (catalog: FactoryMaterial[], ref: MaterialReference) => catalog.find(m => same(m, ref) && available(m));

/** Caller obtains this exact snapshot from the approved catalog or revision API.
 * Preserve all unknown definition fields for advanced review; strip only known
 * server-owned envelope fields. This helper grants no publication authority. */
export function templateDefinition(app: FactoryApplication, operation: 'copy' | 'revise'): Record<string, unknown> {
  if (!pin({ id: app.id, version: app.version, sha256: app.sha256 }) || !['copy', 'revise'].includes(operation)) {
    throw new Error('模板精确版本无法核对，请重新读取已批准应用。');
  }
  const result = structuredClone(app) as unknown as Record<string, unknown>;
  for (const field of ['version', 'sha256', 'createdAt', 'schema', 'origin']) delete result[field];
  if (operation === 'copy') delete result.id;
  return result;
}

export function inspectTemplate(value: unknown, catalog: FactoryMaterial[]): TemplateInspection {
  const result: TemplateInspection = { guided: true, errors: [], warnings: [], modes: [] };
  const unsupported = (message: string) => { result.guided = false; result.warnings.push(`${message}；请使用高级 JSON 编辑，原字段保留。`); };
  const keys = (obj: Record<string, unknown>, allowed: string[], location: string) => {
    if (Object.keys(obj).some(key => !allowed.includes(key))) unsupported(`${location}含表单不支持的字段`);
  };
  const numeric = (obj: Record<string, unknown>, bounds: Record<string, readonly [number, number]>, location: string) => {
    keys(obj, Object.keys(bounds), location);
    for (const [key, n] of Object.entries(obj)) {
      const bound = bounds[key];
      if (bound && (!Number.isSafeInteger(n) || Number(n) < bound[0] || Number(n) > bound[1])) result.errors.push(`${location}.${key} 必须是 ${bound[0]}–${bound[1]} 的整数。`);
    }
  };
  if (!record(value)) { unsupported('定义不是对象'); return result; }
  try { if (new TextEncoder().encode(JSON.stringify(value)).length > 131072) result.errors.push('定义超过 128 KiB，请缩小范围。'); }
  catch { unsupported('定义不能表示为 JSON'); return result; }
  keys(value, ['id', 'name', 'description', 'discoveryKeywords', 'defaultForDiscovery', 'defaultMode', 'modes'], '定义');
  if (value.id !== undefined && !identifier(value.id)) result.errors.push('应用标识必须是 1–100 个字母、数字或 _ . : -。');
  if (typeof value.name !== 'string' || !value.name.trim() || [...value.name].length > 120) result.errors.push('名称需要 1–120 个字符。');
  if (typeof value.description !== 'string' || [...value.description].length > 2000) result.errors.push('描述最多 2000 个字符。');
  if (!strings(value.discoveryKeywords) || value.discoveryKeywords.length > 30 || value.discoveryKeywords.some(word => !word.trim() || [...word].length > 100)) result.errors.push('发现关键词最多 30 项，每项 1–100 个字符。');
  if (typeof value.defaultForDiscovery !== 'boolean') result.errors.push('默认候选必须是明确的是或否。');
  if (!record(value.modes) || Object.keys(value.modes).length < 1 || Object.keys(value.modes).length > 8) { unsupported('执行方式数量或结构无法核对'); return result; }
  if (!identifier(value.defaultMode) || !Object.hasOwn(value.modes, value.defaultMode)) result.errors.push('默认执行方式必须存在于此模板。');
  for (const [name, mode] of Object.entries(value.modes)) {
    if (!identifier(name) || !record(mode) || !pins(mode.materialRefs) || !strings(mode.capabilities)
        || !record(mode.budget) || !record(mode.config) || !strings(mode.toolOrder)
        || !record(mode.materialChoices) || !Array.isArray(mode.connectionRequirements)) { unsupported(`方式 ${name} 的结构无法核对`); continue; }
    const capabilities = mode.capabilities;
    keys(mode, ['materialRefs', 'materialChoices', 'capabilities', 'budget', 'config', 'toolOrder', 'connectionRequirements'], `方式 ${name}`);
    if (!mode.materialRefs.length || mode.materialRefs.length > 30 || new Set(mode.materialRefs.map(templateRefKey)).size !== mode.materialRefs.length) result.errors.push(`方式 ${name} 需要 1–30 项不重复的精确材料。`);
    if (!mode.capabilities.length || mode.capabilities.length > 30) result.errors.push(`方式 ${name} 的能力范围数量无效。`);
    numeric(mode.budget, budgetBounds, `${name} 预算`); numeric(mode.config, configBounds, `${name} 配置`);
    const view: TemplateModeView = { name, materials: [], toolNames: [], slots: [] };
    const closure = new Map<string, FactoryMaterial>();
    let visits = 0;
    const visit = (ref: MaterialReference, ancestors = new Set<string>()) => {
      const key = templateRefKey(ref); const material = find(catalog, ref);
      if (!material) { result.warnings.push(`方式 ${name} 的精确材料 ${ref.id} v${ref.version} 未在当前可用目录中；不能据此确认发布可用。`); return; }
      if (ancestors.has(key) || ++visits > 120) { result.errors.push(`方式 ${name} 的材料依赖循环或超过表单检查上限。`); return; }
      if (closure.has(key)) return;
      const next = new Set(ancestors); next.add(key);
      for (const dependency of material.dependencies) visit(dependency, next);
      closure.set(key, material);
    };
    for (const ref of mode.materialRefs) { view.materials.push({ ref: structuredClone(ref), material: structuredClone(find(catalog, ref) ?? null) }); visit(ref); }
    for (const material of closure.values()) {
      if (material.permissions.some(cap => !capabilities.includes(cap))) result.errors.push(`方式 ${name} 的材料 ${material.id} 超出原能力范围；表单不会新增权限。`);
      if (material.kind === 'tool' && !view.toolNames.includes(material.content)) view.toolNames.push(material.content);
    }
    if (mode.toolOrder.length > 30 || new Set(mode.toolOrder).size !== mode.toolOrder.length || mode.toolOrder.some(tool => !view.toolNames.includes(tool)) || mode.toolOrder.length && mode.toolOrder.length !== view.toolNames.length) result.errors.push(`方式 ${name} 的工具顺序须恰好包含全部选定工具，或留空使用原材料顺序。`);
    const defaults = new Set<string>();
    if (Object.keys(mode.materialChoices).length > 12) result.errors.push(`方式 ${name} 最多允许 12 个已有槽位。`);
    for (const [slotName, slot] of Object.entries(mode.materialChoices)) {
      if (!record(slot) || !kinds.includes(String(slot.kind)) || !pin(slot.defaultRef) || !pins(slot.allowedRefs)) { unsupported(`方式 ${name} 槽位 ${slotName} 无法核对`); continue; }
      keys(slot, ['kind', 'defaultRef', 'allowedRefs'], `槽位 ${slotName}`);
      const defaultKey = templateRefKey(slot.defaultRef);
      if (!slotName || slotName.length > 100 || !slot.allowedRefs.length || slot.allowedRefs.length > 8 || !slot.allowedRefs.some(ref => same(ref, slot.defaultRef as MaterialReference)) || !mode.materialRefs.some(ref => same(ref, slot.defaultRef as MaterialReference)) || defaults.has(defaultKey)) result.errors.push(`槽位 ${slotName} 的默认材料必须在固定材料和允许选项中，且不能与其他槽位重叠。`);
      defaults.add(defaultKey);
      for (const ref of slot.allowedRefs) {
        const material = find(catalog, ref);
        if (!material) result.warnings.push(`槽位 ${slotName} 的精确选项 ${ref.id} v${ref.version} 当前不可用。`);
        else if (material.kind !== slot.kind) result.errors.push(`槽位 ${slotName} 的材料类别不匹配。`);
      }
      view.slots.push({ name: slotName, kind: slot.kind as FactoryMaterial['kind'], defaultRef: structuredClone(slot.defaultRef), allowedRefs: structuredClone(slot.allowedRefs) });
    }
    const connectionNames = new Set<string>();
    if (mode.connectionRequirements.length > 12) result.errors.push(`方式 ${name} 最多允许 12 个连接要求。`);
    for (const connection of mode.connectionRequirements) {
      if (!record(connection) || !identifier(connection.name) || !['model', 'tool', 'knowledge', 'environment', 'orx'].includes(String(connection.kind)) || !strings(connection.requiredCapabilities) || typeof connection.required !== 'boolean') { unsupported(`方式 ${name} 的可信连接要求无法核对`); continue; }
      keys(connection, ['name', 'kind', 'requiredCapabilities', 'required'], '可信连接要求');
      if (connectionNames.has(connection.name) || connection.requiredCapabilities.length > 30 || connection.requiredCapabilities.some(cap => !capabilities.includes(cap))) result.errors.push(`方式 ${name} 的连接要求重名或超出原能力范围。`);
      connectionNames.add(connection.name);
    }
    result.modes.push(view);
  }
  return result;
}

export function updateTemplate(definition: Record<string, unknown>, change: TemplateChange, catalog: FactoryMaterial[]): Record<string, unknown> {
  if (!inspectTemplate(definition, catalog).guided) throw new Error('此定义含表单不支持的结构，请使用高级 JSON 编辑。');
  const next = structuredClone(definition);
  if (change.kind === 'metadata') {
    if (!['name', 'description', 'discoveryKeywords', 'defaultMode', 'defaultForDiscovery'].includes(change.field)) throw new Error('此字段不在引导编辑范围。');
    next[change.field] = structuredClone(change.value); return next;
  }
  if (!record(next.modes) || !Object.hasOwn(next.modes, change.mode) || !record(next.modes[change.mode])) throw new Error('只能修改模板已有执行方式。');
  const mode = next.modes[change.mode] as Record<string, unknown>;
  if (change.kind === 'budget' || change.kind === 'config') {
    const bounds = change.kind === 'budget' ? budgetBounds : configBounds;
    if (!Object.hasOwn(bounds, change.field) || !record(mode[change.kind]) || typeof change.value !== 'number') throw new Error('未知预算或配置字段须高级编辑。');
    (mode[change.kind] as Record<string, unknown>)[change.field] = change.value;
  } else if (change.kind === 'modeRefs') {
    const previous = mode.materialRefs as MaterialReference[];
    if (!pins(change.refs) || change.refs.some(ref => !find(catalog, ref) && !previous.some(old => same(old, ref)))) throw new Error('只能新增当前目录中的精确已发布材料版本。');
    mode.materialRefs = structuredClone(change.refs);
  } else if (change.kind === 'slotDefault') {
    if (!record(mode.materialChoices) || !Object.hasOwn(mode.materialChoices, change.slot)) throw new Error('只能调整模板已有槽位。');
    const slot = mode.materialChoices[change.slot];
    if (!record(slot) || !pins(slot.allowedRefs) || !pin(slot.defaultRef) || !pin(change.ref) || !slot.allowedRefs.some(ref => same(ref, change.ref)) || !find(catalog, change.ref)) throw new Error('默认项必须是原槽位允许的精确可用材料。');
    mode.materialRefs = (mode.materialRefs as MaterialReference[]).map(ref => same(ref, slot.defaultRef as MaterialReference) ? structuredClone(change.ref) : ref);
    slot.defaultRef = structuredClone(change.ref);
  } else if (change.kind === 'toolOrder') {
    if (!strings(change.tools)) throw new Error('工具顺序必须是选定工具列表。');
    mode.toolOrder = [...change.tools];
  } else throw new Error('此操作不在引导编辑范围。');
  return next;
}
