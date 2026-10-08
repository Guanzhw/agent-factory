import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { ApplicationTemplateEditor } from '../web/ApplicationTemplateEditor.js';
import type { FactoryMaterial } from '../web/models.js';
const tool: FactoryMaterial = { id: 'tool-read', version: 1, kind: 'tool', name: '读取公开来源', description: '受控读取', content: 'read_source',
  sha256: 'a'.repeat(64), license: 'MIT', origin: 'fixture', dependencies: [], compatibility: ['native'], permissions: ['read'], inputSchema: {}, outputSchema: {}, archived: false, published: true, createdAt: '' };
const ref = { id: tool.id, version: tool.version, sha256: tool.sha256 };
function definition() {
  return { name: '公开来源应用', description: '核对出处', discoveryKeywords: ['公开来源'], defaultForDiscovery: false, defaultMode: 'literature', modes: {
    literature: { materialRefs: [ref], materialChoices: { reader: { kind: 'tool', defaultRef: ref, allowedRefs: [ref] } }, capabilities: ['read'],
      budget: { toolCalls: 8, maxDepth: 2, maxChildren: 4, experimentSeconds: 8, outputBytes: 65536 },
      config: { askScopeBelowLength: 0, experimentDurationSeconds: 5 }, toolOrder: ['read_source'], connectionRequirements: [] } } };
}
describe('guided application template rendering', () => {
  it('shows Chinese fields, fixed material slots, bounded budgets and preserved scope without writes', () => {
    const onChange = vi.fn(); const original = definition(); const before = structuredClone(original);
    const html = renderToStaticMarkup(createElement(ApplicationTemplateEditor, { definition: original, materials: [tool], onChange }));
    for (const label of ['应用名称', '应用说明', '发现关键词 1', '默认执行方式', '编辑执行方式', '固定材料', '默认材料 reader', '预算 工具调用次数', '上移工具 read_source', '另一位管理员审查发布', '保留的能力、连接与准确版本']) expect(html).toContain(label);
    expect(html).not.toContain('type="submit"'); expect(onChange).not.toHaveBeenCalled(); expect(original).toEqual(before);
  });
  it('disables guided controls while saving or authority is unavailable', () => {
    const html = renderToStaticMarkup(createElement(ApplicationTemplateEditor, { definition: definition(), materials: [tool], onChange: () => {}, disabled: true }));
    expect(html).toContain('<fieldset disabled=""'); expect(html).toContain('aria-label="预算 工具调用次数"');
  });
  it('keeps unknown extensions advanced-only without dropping or rendering them as active markup', () => {
    const original = { ...definition(), futureConfiguration: '<script>never-run</script>' };
    const onChange = vi.fn(); const html = renderToStaticMarkup(createElement(ApplicationTemplateEditor, { definition: original, materials: [tool], onChange }));
    expect(html).toContain('高级 JSON'); expect(html).not.toContain('aria-label="应用名称"'); expect(html).not.toContain('<script>'); expect(onChange).not.toHaveBeenCalled(); expect(original.futureConfiguration).toBe('<script>never-run</script>');
  });
  it('exposes missing pinned materials without fabricating a replacement or permission', () => {
    const html = renderToStaticMarkup(createElement(ApplicationTemplateEditor, { definition: definition(), materials: [], onChange: () => {} }));
    expect(html).toContain('草稿需要核对'); expect(html).toContain('tool-read');
    expect(html).toContain('最终由服务端检查');
  });
});
