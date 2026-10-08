import { describe, expect, it } from 'vitest';
import { budgetBounds, configBounds, inspectTemplate, templateDefinition, updateTemplate } from '../web/applicationTemplateState.js';
import type { FactoryApplication, FactoryMaterial, MaterialReference } from '../web/models.js';
const ref = (id: string, version = 1): MaterialReference => ({ id, version, sha256: (version === 1 ? 'a' : 'b').repeat(64) });
const material = (id: string, kind: FactoryMaterial['kind'], content = id): FactoryMaterial => ({ ...ref(id), kind, content,
  name: id, description: '', dependencies: [], permissions: ['read'], published: true, archived: false,
  compatibility: [], inputSchema: {}, outputSchema: {}, license: 'MIT', origin: 'controlled-fixture', createdAt: '2026-10-04T00:00:00Z' });
const catalog = [material('model', 'model'), material('prompt', 'prompt'), material('prompt-alt', 'prompt'),
  material('tool', 'tool', 'checksum'), material('environment', 'environment'), material('knowledge', 'knowledge'), material('skill', 'skill')];
const scope = () => ({ materialRefs: catalog.filter(m => m.id !== 'prompt-alt').map(m => ref(m.id)),
  capabilities: ['read'], budget: { toolCalls: 8, maxDepth: 2, maxChildren: 4, experimentSeconds: 8, outputBytes: 65536 },
  config: { askScopeBelowLength: 0, experimentDurationSeconds: 5 }, toolOrder: ['checksum'],
  materialChoices: { prompt: { kind: 'prompt', defaultRef: ref('prompt'), allowedRefs: [ref('prompt'), ref('prompt-alt')] } },
  connectionRequirements: [{ name: 'source', kind: 'knowledge', requiredCapabilities: ['read'], required: false }] });
const app = (): FactoryApplication => ({ id: 'research', version: 3, sha256: 'c'.repeat(64), name: '原模板', description: '完整范围',
  discoveryKeywords: ['研究'], defaultForDiscovery: false, defaultMode: 'literature',
  modes: { literature: scope(), experiment: scope() } as FactoryApplication['modes'] });
const draft = () => templateDefinition(app(), 'copy');

describe('guided application template contract', () => {
  it('roundtrips all definition fields and preserves the exact revision identity without mutating source', () => {
    const source = { ...app(), schema: 1, createdAt: '2026-10-04T00:00:00Z', origin: 'manager-authored' };
    const previous = structuredClone(source);
    const copied = templateDefinition(source, 'copy'); const revised = templateDefinition(source, 'revise');
    expect(copied).toEqual({ name: source.name, description: source.description, discoveryKeywords: source.discoveryKeywords,
      defaultForDiscovery: false, defaultMode: source.defaultMode, modes: source.modes });
    expect(revised).toEqual({ ...copied, id: source.id });
    (copied.modes as Record<string, unknown>).literature = {};
    expect(source).toEqual(previous);
    expect(() => templateDefinition({ ...source, sha256: 'unknown' }, 'copy')).toThrow('精确版本');
  });
  it('keeps unknown fields losslessly and routes unsupported definitions to advanced-only', () => {
    const source = { ...app(), futureTop: { exact: 1 } };
    source.modes.literature.config.futureConfig = { preserve: true };
    const value = templateDefinition(source, 'copy'); const before = structuredClone(value);
    expect(inspectTemplate(value, catalog).guided).toBe(false);
    expect(inspectTemplate(value, catalog).warnings.join('')).toContain('高级 JSON');
    expect(() => updateTemplate(value, { kind: 'metadata', field: 'name', value: '新名称' }, catalog)).toThrow('高级 JSON');
    expect(value).toEqual(before); expect(value.futureTop).toEqual({ exact: 1 });
  });
  it('exposes six material kinds, existing slots and selected tool names', () => {
    const result = inspectTemplate(draft(), catalog);
    expect(result.guided).toBe(true); expect(result.errors).toEqual([]); expect(result.warnings).toEqual([]);
    expect(result.modes[0].materials.map(x => x.material?.kind).sort()).toEqual(['environment', 'knowledge', 'model', 'prompt', 'skill', 'tool']);
    expect(result.modes[0].toolNames).toEqual(['checksum']); expect(result.modes[0].slots[0].allowedRefs).toEqual([ref('prompt'), ref('prompt-alt')]);
  });
  it('changes slot default and fixed reference together, keeps modes/config/connections unchanged', () => {
    const original = draft(); const value = updateTemplate(original, { kind: 'slotDefault', mode: 'literature', slot: 'prompt', ref: ref('prompt-alt') }, catalog);
    const modes = value.modes as FactoryApplication['modes'];
    expect(modes.literature.materialRefs).toContainEqual(ref('prompt-alt')); expect(modes.literature.materialRefs).not.toContainEqual(ref('prompt'));
    expect(modes.literature.materialChoices.prompt.defaultRef).toEqual(ref('prompt-alt'));
    expect(modes.literature.connectionRequirements).toEqual(scope().connectionRequirements);
    expect(modes.experiment).toEqual(scope()); expect(original).toEqual(draft()); expect(inspectTemplate(value, catalog).errors).toEqual([]);
    expect(() => updateTemplate(original, { kind: 'slotDefault', mode: 'literature', slot: 'prompt', ref: ref('knowledge') }, catalog)).toThrow('原槽位');
  });
  it('warns on missing exact hashes and withdrawn materials, never substitutes latest version', () => {
    const current = catalog.map(m => m.id === 'prompt' ? { ...m, sha256: 'd'.repeat(64) } : m);
    const result = inspectTemplate(draft(), current);
    expect(result.warnings.join('')).toContain('精确材料 prompt');
    expect(result.modes[0].materials.find(x => x.ref.id === 'prompt')?.material).toBeNull();
    const withdrawn = catalog.map(m => ({ ...m, published: false }));
    expect(() => updateTemplate(draft(), { kind: 'modeRefs', mode: 'literature', refs: [ref('tool', 2)] }, withdrawn)).toThrow('已发布材料');
  });
  it('lets an author remove multiple unavailable refs incrementally without adding unknown pins', () => {
    const current = catalog.filter(m => !['knowledge', 'skill'].includes(m.id));
    const first = updateTemplate(draft(), { kind: 'modeRefs', mode: 'literature', refs: scope().materialRefs.filter(r => r.id !== 'knowledge') }, current);
    const second = updateTemplate(first, { kind: 'modeRefs', mode: 'literature', refs: (first.modes as FactoryApplication['modes']).literature.materialRefs.filter(r => r.id !== 'skill') }, current);
    expect(inspectTemplate(first, current).warnings.join('')).toContain('skill');
    expect(inspectTemplate(second, current).modes[0].materials.every(row => row.material !== null)).toBe(true);
    expect(() => updateTemplate(second, { kind: 'modeRefs', mode: 'literature', refs: [ref('missing')] }, current)).toThrow('已发布材料');
  });
  it('validates all Python budget/config bounds and safe integers without mutating editable fields', () => {
    for (const [kind, bounds] of [['budget', budgetBounds], ['config', configBounds]] as const) {
      for (const [field, [min, max]] of Object.entries(bounds)) {
        for (const value of [min, max]) expect(inspectTemplate(updateTemplate(draft(), { kind, mode: 'literature', field, value }, catalog), catalog).errors).toEqual([]);
        for (const value of [min - 1, max + 1, 1.2, NaN, Infinity]) expect(inspectTemplate(updateTemplate(draft(), { kind, mode: 'literature', field, value }, catalog), catalog).errors.join('')).toContain(field);
      }
    }
    expect(() => updateTemplate(draft(), { kind: 'config', mode: 'literature', field: 'arbitraryCommand', value: 1 }, catalog)).toThrow('高级编辑');
  });
  it('preserves original capabilities and reports unauthorized material dependencies', () => {
    const extra = material('powerful', 'tool', 'shell'); extra.permissions = ['shell:write'];
    const value = updateTemplate(draft(), { kind: 'modeRefs', mode: 'literature', refs: [...scope().materialRefs, ref('powerful')] }, [...catalog, extra]);
    expect((value.modes as FactoryApplication['modes']).literature.capabilities).toEqual(['read']);
    expect(inspectTemplate(value, [...catalog, extra]).errors.join('')).toContain('超出原能力范围');
    const dependency = material('dependency', 'tool', 'verify');
    const current = catalog.map(m => m.id === 'skill' ? { ...m, dependencies: [ref('dependency')] } : m);
    expect(inspectTemplate(draft(), [...current, dependency]).modes[0].toolNames).toEqual(['checksum', 'verify']);
  });
  it('checks existing mode/default/tool-order and never silently creates mode or tool authority', () => {
    expect(() => updateTemplate(draft(), { kind: 'budget', mode: '__proto__', field: 'toolCalls', value: 8 }, catalog)).toThrow('已有执行方式');
    for (const tools of [['new_tool'], ['checksum', 'checksum']]) {
      expect(inspectTemplate(updateTemplate(draft(), { kind: 'toolOrder', mode: 'literature', tools }, catalog), catalog).errors.join('')).toContain('工具顺序');
    }
    expect(inspectTemplate(updateTemplate(draft(), { kind: 'toolOrder', mode: 'literature', tools: [] }, catalog), catalog).errors).toEqual([]);
    expect(inspectTemplate(updateTemplate(draft(), { kind: 'metadata', field: 'defaultMode', value: 'absent' }, catalog), catalog).errors.join('')).toContain('默认执行方式');
  });
  it('permits interim form input but reports readable name/keyword errors for save gating', () => {
    const value = updateTemplate(draft(), { kind: 'metadata', field: 'name', value: '' }, catalog);
    expect(inspectTemplate(value, catalog).guided).toBe(true); expect(inspectTemplate(value, catalog).errors.join('')).toContain('名称');
    expect(inspectTemplate(updateTemplate(draft(), { kind: 'metadata', field: 'discoveryKeywords', value: [''] }, catalog), catalog).errors.join('')).toContain('关键词');
  });
});
