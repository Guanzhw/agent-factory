import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { MaterialPicker } from '../web/MaterialPicker.js';
import { catalogMaterials, exactMaterialKey, materialKinds, materialReference, runtimeBindingSummary, selectionIssues, toggleMaterialSelection } from '../web/materialCatalogState.js';
import type { FactoryMaterial } from '../web/models.js';

function material(overrides: Partial<FactoryMaterial> = {}): FactoryMaterial {
  return { id: 'source', version: 1, kind: 'knowledge', name: '公开文献', description: '带出处的摘要', content: '',
    sha256: 'a'.repeat(64), license: 'MIT', origin: 'fixture', dependencies: [], compatibility: ['native'],
    permissions: [], inputSchema: {}, outputSchema: {}, archived: false, published: true, createdAt: '', ...overrides };
}

describe('exact approved material catalog selection', () => {
  it('filters six types and public metadata without mutating catalog', () => {
    const materials = materialKinds.map(kind => material({ id: kind, kind }));
    expect(catalogMaterials(materials)).toHaveLength(6);
    expect(catalogMaterials(materials, '带出处', 'knowledge')).toEqual([materials[3]]);
    expect(catalogMaterials(materials, ' MODEL ')).toEqual([materials[4]]);
    expect(catalogMaterials([material({ published: false }), material({ archived: true }),
      material({ governance: { state: 'withdrawn' } })])).toEqual([]);
  });
  it('never substitutes new version or changed hash for unavailable exact selection', () => {
    const original = materialReference(material());
    const replacements = [material({ version: 2 }), material({ sha256: 'b'.repeat(64) })];
    expect(selectionIssues(replacements, [original])[0]?.unavailable).toBe(true);
    expect(selectionIssues([material({ governance: { state: 'withdrawn' } })], [original])[0]?.unavailable).toBe(true);
    expect(original.sha256).toBe('a'.repeat(64));
  });
  it('returns only public exact references with no automatic dependency or permission changes', () => {
    const dependency = materialReference(material({ id: 'dependency' }));
    const source = material({ dependencies: [dependency], permissions: ['research:read'] });
    const selected = toggleMaterialSelection([], source, true);
    expect(selected).toEqual([materialReference(source)]);
    expect(Object.keys(selected[0]!)).toEqual(['id', 'version', 'sha256']);
    expect(selectionIssues([source], selected)[0]?.missingDependencies).toEqual([dependency]);
    expect(selectionIssues([source], [...selected, { ...dependency, sha256: 'c'.repeat(64) }])[0]?.missingDependencies).toEqual([dependency]);
    expect(toggleMaterialSelection(selected, source, true)).toEqual(selected);
    expect(toggleMaterialSelection(selected, source, false)).toEqual([]);
    expect(toggleMaterialSelection([], material({ published: false }), true)).toEqual([]);
  });
  it('uses collision-free exact keys and copies returned references', () => {
    expect(exactMaterialKey({ id: 'a:1', version: 2, sha256: 'b' })).not.toBe(exactMaterialKey({ id: 'a', version: 1, sha256: '2:b' }));
    const selected = [materialReference(material())];
    const copy = toggleMaterialSelection(selected, material(), true);
    copy[0]!.id = 'changed';
    expect(selected[0]!.id).toBe('source');
  });
  it('shows only registered binding summary without content or installation actions', () => {
    const bound = { ...material(), runtimeBinding: { adapterId: 'controlled-reader', revision: 'v1', privateField: 'not-rendered' } };
    expect(runtimeBindingSummary(bound)).toBe('controlled-reader · v1');
    const html = renderToStaticMarkup(createElement(MaterialPicker, { materials: [bound], selected: [], label: '模式素材', onChange: () => {} }));
    expect(html).toContain('controlled-reader');
    expect(html).not.toContain('not-rendered');
  });
  it('renders accessible grouping, exact missing selections and disabled controls', () => {
    const missing = materialReference(material({ id: '<missing>' }));
    const html = renderToStaticMarkup(createElement(MaterialPicker, { materials: [material()], selected: [missing], label: '模式素材', disabled: true, onChange: () => {} }));
    expect(html).toContain('<legend>模式素材</legend>');
    expect(html).toContain('搜索素材名称、编号或说明');
    expect(html).toContain('type="checkbox"');
    expect(html).toContain('此精确版本已撤回');
    expect(html).toContain('disabled=""');
    expect(html).toContain('&lt;missing&gt;');
    expect(html).not.toContain('<missing>');
  });
});
