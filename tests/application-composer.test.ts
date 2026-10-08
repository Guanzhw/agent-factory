import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApplicationComposer, ComposerProposalScope, recoverComposerProposal } from '../web/ApplicationComposer.js';
import { api } from '../web/api.js';
import type { AssemblyCandidate, AssemblyProposal, Plan } from '../web/models.js';

const first = '11111111-1111-4111-8111-111111111111';
const second = '22222222-2222-4222-8222-222222222222';
const applicationRef = { id: 'public-fixture', version: 1, sha256: 'a'.repeat(64) };
function candidate(): AssemblyCandidate {
  return { application: applicationRef.id, applicationRef, mode: 'literature', normalizedGoal: '比较公开证据',
    materialRefs: [], materials: [], tools: ['read_source'], capabilities: ['read:public'],
    budget: { toolCalls: 8, maxDepth: 2, maxChildren: 4, experimentSeconds: 8, outputBytes: 65536 },
    config: { internalOption: 'fixture-only' }, instructions: 'Bounded fixture', status: 'blocked', missing: ['请选择必需的模型连接'],
    policy: {}, syntheticFixture: true, executionBindings: { model: { adapterId: 'fixture-model', revision: 'r1' } },
    bindingManifest: {}, fingerprint: 'b'.repeat(64) };
}
function proposal(id = first): AssemblyProposal {
  return { id, ownerId: 'alice', createdAt: '2026-10-08T00:00:00Z', parentId: null, input: { goal: '比较公开证据' },
    candidate: candidate(), selection: { method: 'explicit-application', matchedKeywords: [] }, fingerprint: 'c'.repeat(64),
    state: 'pending', planId: null, allowedActions: ['revise', 'accept', 'reject'] };
}
function renderComposer() {
  return renderToStaticMarkup(createElement(ApplicationComposer, { user: { id: 'alice', name: 'Alice', role: 'user' },
    busy: '', act: async (_name, work) => { await work(); }, materials: [], targets: [], onCreated: vi.fn() }));
}
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('task-first application composer', () => {
  it('puts the fresh task entry before collapsed history and labels the safe four-step flow', () => {
    const html = renderComposer();
    const history = html.indexOf('<details class="composer-history technical-detail">');
    expect(history).toBeGreaterThan(html.indexOf('</form>'));
    expect(history).toBeLessThan(html.indexOf('我的装配提案'));
    for (const label of ['选择应用', '描述任务', '核对方案', '开始任务', '预览任务方案', '不会开始执行']) expect(html).toContain(label);
    expect(html).toContain('aria-current="step"');
    expect(html).toMatch(/<textarea[^>]*id="research-topic"[^>]*><\/textarea>/);
    expect(html).not.toContain('open=""');
  });
  it('keeps a valid saved owner pointer as an explicit recovery action without displacing fresh input', () => {
    const getItem = vi.fn((key: string) => key === 'factory-proposal-v1:alice' ? first : null);
    const setItem = vi.fn(); const removeItem = vi.fn();
    vi.stubGlobal('window', { sessionStorage: { getItem, setItem, removeItem } });
    const recover = vi.spyOn(api, 'recoverProposal'); const propose = vi.spyOn(api, 'propose'); const instantiate = vi.spyOn(api, 'instantiate');
    const html = renderComposer();
    expect(getItem).toHaveBeenCalledWith('factory-proposal-v1:alice');
    expect(html.indexOf('继续上次保存的任务')).toBeGreaterThan(html.indexOf('<details class="composer-history'));
    expect(html).toMatch(/<textarea[^>]*id="research-topic"[^>]*><\/textarea>/);
    for (const operation of [recover, propose, instantiate, setItem, removeItem]) expect(operation).not.toHaveBeenCalled();
  });
  it('ignores malformed recovery pointers and tolerates unavailable storage', () => {
    vi.stubGlobal('window', { sessionStorage: { getItem: () => '../foreign-record' } });
    expect(renderComposer()).not.toContain('继续上次保存的任务');
    vi.stubGlobal('window', { sessionStorage: { getItem: () => { throw new Error('storage unavailable'); } } });
    expect(renderComposer()).toContain('预览任务方案');
    expect(renderComposer()).not.toContain('继续上次保存的任务');
  });
  it('keeps tools, permission boundaries, budgets and missing requirements outside technical disclosure', () => {
    const value = candidate(); const original = structuredClone(value);
    const html = renderToStaticMarkup(createElement(ComposerProposalScope, { candidate: value }));
    const technicalStart = html.indexOf('<details class="technical-detail composer-advanced">');
    expect(technicalStart).toBeGreaterThan(0);
    for (const label of ['不会调用付费模型', '使用的工具', 'read_source', '能力与权限边界', 'read:public', '固定预算上限', '工具调用', '请选择必需的模型连接']) {
      expect(html.slice(0, technicalStart)).toContain(label);
    }
    for (const label of ['六类固定材料', 'fixture-model@r1', 'internalOption', 'fixture-only']) expect(html.slice(technicalStart)).toContain(label);
    expect(html).not.toContain('open=""'); expect(value).toEqual(original);
  });
  it('shows simple fixed inputs with their published labels and escapes external text', () => {
    const value = candidate();
    value.inputSchema = { type: 'object', properties: { topic: { type: 'string', title: '比较范围', maxLength: 100 } }, additionalProperties: false };
    value.inputValues = { topic: '<script>example</script>' };
    const html = renderToStaticMarkup(createElement(ComposerProposalScope, { candidate: value }));
    const technicalStart = html.indexOf('<details class="technical-detail');
    expect(html.slice(0, technicalStart)).toContain('比较范围');
    expect(html.slice(0, technicalStart)).toContain('&lt;script&gt;example&lt;/script&gt;');
    expect(html).not.toContain('<script>');
  });
});

describe('explicit proposal recovery', () => {
  it('follows an owner-matched revision chain and returns the original accepted plan without mutation', async () => {
    const parent = { ...proposal(), state: 'revised' as const, revisedBy: second };
    const plan: Plan = { id: 'plan-fixture', fingerprint: 'd'.repeat(64), normalizedGoal: '比较公开证据', materialRefs: [], capabilities: [], missing: [], status: 'ready', createdAt: '2026-10-08T00:00:00Z' };
    const child = { ...proposal(second), parentId: first, state: 'accepted' as const, planId: plan.id };
    const result = { proposal: child, plan };
    const load = vi.fn().mockResolvedValueOnce({ proposal: parent, plan: null }).mockResolvedValueOnce(result);
    const before = structuredClone({ parent, child, plan });
    expect(await recoverComposerProposal('alice', first, load)).toBe(result);
    expect(load.mock.calls).toEqual([[first], [second]]);
    expect({ parent, child, plan }).toEqual(before);
  });
  it('rejects owner, record-id and predecessor mismatches before accepting a recovered record', async () => {
    for (const change of [{ ownerId: 'bob' }, { id: second }]) {
      const load = vi.fn().mockResolvedValue({ proposal: { ...proposal(), ...change }, plan: null });
      await expect(recoverComposerProposal('alice', first, load)).rejects.toThrow('无法核对');
      expect(load).toHaveBeenCalledTimes(1);
    }
    const load = vi.fn().mockResolvedValueOnce({ proposal: { ...proposal(), state: 'revised', revisedBy: second }, plan: null })
      .mockResolvedValueOnce({ proposal: { ...proposal(second), parentId: 'foreign-parent' }, plan: null });
    await expect(recoverComposerProposal('alice', first, load)).rejects.toThrow('无法核对');
  });
  it('does not follow malformed, absent or cyclic revision pointers', async () => {
    for (const revisedBy of [undefined, '../foreign', first]) {
      const load = vi.fn().mockResolvedValue({ proposal: { ...proposal(), state: 'revised', revisedBy }, plan: null });
      await expect(recoverComposerProposal('alice', first, load)).rejects.toThrow('无法核对');
      expect(load).toHaveBeenCalledTimes(1);
    }
    const load = vi.fn();
    await expect(recoverComposerProposal('alice', 'not-a-pointer', load)).rejects.toThrow('无法核对');
    expect(load).not.toHaveBeenCalled();
  });
  it('bounds revision traversal and reports a recoverable history choice instead of accepting an unresolved revision', async () => {
    const ids = Array.from({ length: 11 }, (_, i) => `${String(i).padStart(8, '0')}-1111-4111-8111-111111111111`);
    const load = vi.fn(async (id: string) => { const index = ids.indexOf(id); return { proposal: { ...proposal(id), state: 'revised' as const, parentId: index ? ids[index - 1] : null, revisedBy: ids[index + 1] }, plan: null }; });
    await expect(recoverComposerProposal('alice', ids[0], load)).rejects.toThrow('选择较新的提案');
    expect(load).toHaveBeenCalledTimes(9);
  });
});
