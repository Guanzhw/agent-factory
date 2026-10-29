// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { beforeEach, afterEach, it, expect, vi } from 'vitest';
import { Workspace } from '../web/composition.js';
import { api } from '../web/api.js';
import { ownerModelApi } from '../web/ownerModelApi.js';
import { readWorkspaceRoute, workspaceUrl } from '../web/workspaceNavigation.js';
import type { ApplicationVersion, AssemblyProposal, FactoryApplication, Plan, UserConnection } from '../web/models.js';

const owner = { id: 'alice', name: 'Synthetic Alice', role: 'user' as const };
const application: FactoryApplication = {
  id: 'qa-template', version: 1, sha256: 'a'.repeat(64), name: 'QA 校验文件', description: '仅组件测试的模板，不执行模型。',
  discoveryKeywords: ['校验'], defaultForDiscovery: true, defaultMode: 'check',
  modes: { check: { materialRefs: [], materialChoices: {}, capabilities: [], budget: { toolCalls: 8, maxDepth: 1, maxChildren: 1, outputBytes: 65536 }, config: {}, toolOrder: [],
    connectionRequirements: [{ name: 'model', kind: 'model', required: true, requiredCapabilities: ['text'] }],
    inputSchema: { type: 'object', properties: { path: { type: 'string', title: '文件路径', maxLength: 200, description: '待校验的工作区文件。' } }, required: ['path'], additionalProperties: false } } },
};
const version: ApplicationVersion = { application, immutableBodyPreserved: true, governance: { author_id: 'author', state: 'published', entry_kind: 'template', bootstrap: false, review_id: null, reason: null } };
const connection: UserConnection = { ref: 'synthetic-model', ownerId: owner.id, kind: 'model', capabilities: ['text'], available: true, taskId: null, registrationRef: 'qa-model', status: 'active', version: 1, fingerprint: 'c'.repeat(64), revision: '1', allowedActions: ['inspect'], createdAt: '', expiresAt: null, revokedAt: null };
let host: HTMLDivElement; let root: Root;
const buttons = (label: string) => [...host.querySelectorAll<HTMLButtonElement>('button')].filter(value => value.textContent === label);
async function click(label: string) { expect(buttons(label).length).toBeGreaterThan(0); await act(async () => buttons(label)[0]!.click()); }
async function settle(assertion: () => void) { await vi.waitFor(async () => { await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); }); assertion(); }); }
async function mount(url = '/?tab=catalog', user = owner) {
  window.history.replaceState(null, '', url);
  await act(async () => root.render(createElement(Workspace, { key: user.id, user, logout: () => {}, sessionBusy: false, sessionError: '' })));
}
async function input(selector: string, value: string) {
  await act(async () => {
    const field = host.querySelector<HTMLInputElement | HTMLTextAreaElement>(selector)!;
    Object.getOwnPropertyDescriptor(field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(field, value);
    field.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto);
  vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('Unexpected request in explicit component fixture'))));
  sessionStorage.clear(); localStorage.clear();
  vi.spyOn(api, 'session').mockResolvedValue(owner);
  vi.spyOn(api, 'status').mockResolvedValue({ mode: 'live', activeWorkers: 0, queuedJobs: 0, maxWorkers: 1, integration: 'synthetic component data', liveEnabled: false });
  vi.spyOn(api, 'jobs').mockResolvedValue({ items: [], nextCursor: null });
  vi.spyOn(api, 'materials').mockResolvedValue([]); vi.spyOn(api, 'executionTargets').mockResolvedValue([]);
  vi.spyOn(api, 'templateCatalog').mockResolvedValue({ items: [application], nextCursor: null });
  vi.spyOn(api, 'inspectApplication').mockResolvedValue(version);
  vi.spyOn(api, 'matchTemplate').mockResolvedValue(application);
  vi.spyOn(api, 'userConnections').mockResolvedValue([]);
  vi.spyOn(api, 'proposalInbox').mockResolvedValue({ schema: 1, ownerId: owner.id, snapshot: false, items: [], nextCursor: null });
  vi.spyOn(api, 'propose'); vi.spyOn(api, 'instantiate');
  vi.spyOn(ownerModelApi, 'capabilities').mockResolvedValue({ enabled: false, providers: [], liveCompatibilityVerified: false });
  vi.spyOn(ownerModelApi, 'list').mockResolvedValue([]);
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('starts from the actual application page, reads an exact template, and returns from model setup with the same input', async () => {
  await mount(); await click('任务模板'); await settle(() => expect(buttons('查看模板')).toHaveLength(1));
  expect(host.querySelector('nav [aria-current="page"]')?.textContent).toBe('应用');
  await click('查看模板'); await settle(() => expect(buttons('用此模板创建任务')).toHaveLength(1));
  expect(api.inspectApplication).toHaveBeenCalledWith('qa-template', 1, expect.any(AbortSignal));
  await click('用此模板创建任务'); await settle(() => expect(host.querySelector<HTMLTextAreaElement>('#task-goal')?.disabled).toBe(false));
  const field = host.querySelector<HTMLInputElement>('[aria-label="文件路径（必需）"]')!;
  expect(field.getAttribute('aria-invalid')).toBe('true');
  expect(document.getElementById(field.getAttribute('aria-describedby')!)?.textContent).toContain('请填写文件路径');
  await input('#task-goal', '检查当前文件，不修改其他目录'); await input('[aria-label="文件路径（必需）"]', 'src/example.py');
  expect(field.hasAttribute('aria-invalid')).toBe(false);
  await click('配置模型并返回'); await settle(() => expect(buttons('返回这次任务')).toHaveLength(1));
  expect(new URL(location.href).searchParams.get('templateReturn')).toBe('1');
  expect(host.querySelector('#task-goal')?.closest('[hidden]')).not.toBeNull();
  vi.mocked(api.userConnections).mockResolvedValue([connection]);
  await click('返回这次任务');
  expect(host.querySelector<HTMLTextAreaElement>('#task-goal')!.value).toBe('检查当前文件，不修改其他目录');
  expect(host.querySelector<HTMLInputElement>('[aria-label="文件路径（必需）"]')!.value).toBe('src/example.py');
  await settle(() => expect(host.querySelector('[aria-label="资源连接 model"]')?.textContent).toContain('qa-model'));
  expect(api.propose).not.toHaveBeenCalled(); expect(api.instantiate).not.toHaveBeenCalled();
  expect(fetch).not.toHaveBeenCalled();
  await click('配置模型并返回');
  await act(async () => { history.back(); await new Promise(resolve => setTimeout(resolve, 20)); });
  expect(host.querySelector('#task-goal')?.closest('[hidden]')).toBeNull();
  expect(host.querySelector<HTMLTextAreaElement>('#task-goal')!.value).toBe('检查当前文件，不修改其他目录');
  await act(async () => { history.forward(); await new Promise(resolve => setTimeout(resolve, 20)); });
  expect(buttons('返回这次任务')).toHaveLength(1);
  await click('我的资源');
  expect(new URL(location.href).searchParams.has('templateReturn')).toBe(false);
  expect(host.querySelector('#task-goal')).toBeNull();
});

it('distinguishes a failed directory from empty and exposes real next steps', async () => {
  vi.mocked(api.templateCatalog).mockRejectedValueOnce(new Error('Synthetic directory unavailable'));
  await mount('/?tab=templates'); await settle(() => expect(host.textContent).toContain('Synthetic directory unavailable'));
  expect(host.textContent).not.toContain('还没有已发布的任务模板');
  vi.mocked(api.templateCatalog).mockResolvedValue({ items: [], nextCursor: null });
  await click('重新读取模板'); await settle(() => expect(host.textContent).toContain('还没有已发布的任务模板'));
  expect(buttons('查看应用')).toHaveLength(1); expect(buttons('前往模板创作')).toHaveLength(1);
  expect(api.propose).not.toHaveBeenCalled();
});

it('can read subsequent pages and returns to the loaded list after inspecting a version', async () => {
  const second = { ...application, id: 'qa-next', name: 'QA 第二页' };
  vi.mocked(api.templateCatalog).mockImplementation(async after => after ? { items: [second], nextCursor: null } : { items: [application], nextCursor: 'cursor-1' });
  vi.mocked(api.inspectApplication).mockResolvedValue({ ...version, application: second });
  await mount('/?tab=templates'); await settle(() => expect(buttons('更多模板')).toHaveLength(1));
  await click('更多模板'); await settle(() => expect(buttons('查看模板')).toHaveLength(2));
  await act(async () => buttons('查看模板')[1]!.click()); await settle(() => expect(buttons('用此模板创建任务')).toHaveLength(1));
  await click('返回模板列表'); await settle(() => expect(buttons('查看模板')).toHaveLength(2));
  expect(host.textContent).toContain(second.name);
  expect(vi.mocked(api.templateCatalog).mock.calls.map(args => args[0])).toEqual([undefined, 'cursor-1']);
});

it.each(['application', 'withdrawn'])('does not create through a %s presentation detail', async state => {
  vi.mocked(api.inspectApplication).mockResolvedValue({ ...version, governance: { ...version.governance, ...(state === 'application' ? { entry_kind: 'application' } : { state: 'withdrawn' }) } });
  await mount('/?tab=templates&templateId=qa-template&templateVersion=1&templateStart=1');
  await settle(() => expect(host.textContent).toContain('这个版本当前不提供普通模板入口'));
  expect(host.querySelector('#task-goal')).toBeNull(); expect(api.propose).not.toHaveBeenCalled();
});

it('does not carry a previous owner draft into a fresh owner or a refreshed page', async () => {
  const url = '/?tab=templates&templateId=qa-template&templateVersion=1&templateStart=1';
  await mount(url); await settle(() => expect(host.querySelector('#task-goal')).not.toBeNull()); await input('#task-goal', 'Alice private input');
  await act(async () => root.render(null)); await mount(url);
  await settle(() => expect(host.querySelector('#task-goal')).not.toBeNull());
  expect(host.querySelector<HTMLTextAreaElement>('#task-goal')!.value).toBe('');
  await input('#task-goal', 'Alice second input');
  const bob = { ...owner, id: 'bob' }; vi.mocked(api.session).mockResolvedValue(bob);
  vi.mocked(api.proposalInbox).mockResolvedValue({ schema: 1, ownerId: bob.id, snapshot: false, items: [], nextCursor: null });
  await mount(url, bob); await settle(() => expect(host.querySelector('#task-goal')).not.toBeNull());
  expect(host.querySelector<HTMLTextAreaElement>('#task-goal')!.value).toBe(''); expect(host.textContent).not.toContain('Alice second input');
});

it('round-trips only valid version pointers and keeps explicit template return separate from research queries', () => {
  const url = new URL('https://fixture.invalid/?tab=models&templateId=qa-template&templateVersion=2&templateStart=1&templateReturn=1');
  const route = readWorkspaceRoute(url, false); expect(route.templateId).toBe('qa-template'); expect(route.templateVersion).toBe('2');
  expect(readWorkspaceRoute(new URL(workspaceUrl(url, route), url), false)).toEqual(route);
  expect(route.modelReturn).toBeUndefined();
  for (const version of ['0', '-1', '1.5', '9007199254740999']) expect(readWorkspaceRoute(new URL(`https://fixture.invalid/?tab=templates&templateId=qa-template&templateVersion=${version}`), false).templateId).toBeUndefined();
  expect(readWorkspaceRoute(new URL('https://fixture.invalid/?tab=tasks&templateReturn=1'), false).templateReturn).toBeUndefined();
});


it('uses the workspace mutation lock for repeated preview and accept clicks, with zero automatic starts', async () => {
  let saved: AssemblyProposal; let savedPlan: Plan | null = null;
  const applicationRef = { id: application.id, version: application.version, sha256: application.sha256 };
  const inputSchema = application.modes.check.inputSchema;
  const plan: Plan = { id: 'test-plan', fingerprint: 'b'.repeat(64), normalizedGoal: '校验文件', applicationRef, materialRefs: [], capabilities: [], missing: [], status: 'ready', createdAt: '', inputSchema, inputValues: { path: 'example.py' } };
  vi.mocked(api.userConnections).mockResolvedValue([connection]);
  vi.mocked(api.propose).mockImplementation(async input => {
    saved = { id: '11111111-1111-4111-8111-111111111111', ownerId: owner.id, input, createdAt: '', parentId: null, planId: null,
      candidate: { application: application.id, applicationRef, mode: 'check', normalizedGoal: input.goal, inputSchema, inputValues: input.inputValues,
        materialRefs: [], materials: [], tools: [], capabilities: [], budget: application.modes.check.budget, config: {}, instructions: '', status: 'ready', missing: [], policy: {}, syntheticFixture: true, executionBindings: null, bindingManifest: {}, fingerprint: 'c'.repeat(64) },
      selection: { method: 'explicit-application', matchedKeywords: [] }, fingerprint: 'd'.repeat(64), state: 'pending', allowedActions: ['revise', 'accept', 'reject'] };
    return saved;
  });
  vi.spyOn(api, 'recoverProposal').mockImplementation(async () => ({ proposal: saved, plan: savedPlan }));
  vi.spyOn(api, 'acceptProposal').mockImplementation(async () => { saved = { ...saved, state: 'accepted', allowedActions: [], planId: plan.id }; savedPlan = plan; return plan; });
  vi.spyOn(api, 'planAuthorization').mockResolvedValue({ ownerId: owner.id, planId: plan.id, planFingerprint: plan.fingerprint, executionAllowed: true, reviewRequired: false, reviewRequestSupported: false, nativeToolConfirmationRequired: false, policy: { name: 'member-self-service', revision: '1', fingerprint: 'e'.repeat(64), review_ttl_seconds: 300, nativeToolConfirmationSeparate: true } });
  await mount('/?tab=templates&templateId=qa-template&templateVersion=1&templateStart=1');
  await settle(() => expect(host.querySelector<HTMLTextAreaElement>('#task-goal')?.disabled).toBe(false));
  await input('#task-goal', '校验文件'); await input('[aria-label="文件路径（必需）"]', 'example.py');
  await act(async () => { const preview = buttons('预览任务方案')[0]!; preview.click(); preview.click(); });
  await settle(() => expect(buttons('确认范围并保存方案')[0]?.disabled).toBe(false));
  expect(api.propose).toHaveBeenCalledTimes(1); expect(api.instantiate).not.toHaveBeenCalled();
  await act(async () => { const accept = buttons('确认范围并保存方案')[0]!; accept.click(); accept.click(); });
  await settle(() => expect(buttons('开始任务')[0]?.disabled).toBe(false));
  expect(api.acceptProposal).toHaveBeenCalledTimes(1); expect(api.instantiate).not.toHaveBeenCalled();
});

it('uses encoded read-only template requests and rejects a mismatched exact version', async () => {
  vi.mocked(api.templateCatalog).mockRestore(); vi.mocked(api.inspectApplication).mockRestore();
  vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ items: [application], nextCursor: null })))
    .mockResolvedValueOnce(new Response(JSON.stringify(version)))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...version, application: { ...application, version: 2 } })));
  const controller = new AbortController();
  await expect(api.templateCatalog('cursor+/=', controller.signal)).resolves.toMatchObject({ items: [application], nextCursor: null });
  expect(fetch).toHaveBeenNthCalledWith(1, '/api/factory/applications/templates?after=cursor%2B%2F%3D', expect.objectContaining({ method: 'GET', signal: controller.signal }));
  await expect(api.inspectApplication(application.id, 1)).resolves.toEqual(version);
  await expect(api.inspectApplication(application.id, 1)).rejects.toThrow('模板版本与所选记录不一致');
  expect(vi.mocked(fetch).mock.calls.every(([, options]) => options?.method === 'GET')).toBe(true);
});


it('matches before proposing so the required input is available without an invalid proposal', async () => {
  await mount('/?tab=templates');
  await settle(() => expect(buttons('根据目标自动匹配')).toHaveLength(1));
  await click('根据目标自动匹配');
  await settle(() => expect(host.querySelector('#task-goal')).not.toBeNull());
  await input('#task-goal', '校验当前文件');
  expect(host.querySelector('[aria-label="文件路径（必需）"]')).toBeNull();
  await click('匹配任务模板');
  await settle(() => expect(host.querySelector('[aria-label="文件路径（必需）"]')).not.toBeNull());
  expect(api.matchTemplate).toHaveBeenCalledExactlyOnceWith('校验当前文件');
  expect(api.propose).not.toHaveBeenCalled(); expect(api.instantiate).not.toHaveBeenCalled();
  expect(buttons('预览任务方案')[0]!.disabled).toBe(true);
  await input('[aria-label="文件路径（必需）"]', 'example.py');
  vi.mocked(api.propose).mockRejectedValue(new Error('Synthetic stop before proposal persistence'));
  await click('预览任务方案');
  await settle(() => expect(api.propose).toHaveBeenCalledTimes(1));
  expect(vi.mocked(api.propose).mock.calls[0][0]).toMatchObject({ goal: '校验当前文件', inputValues: { path: 'example.py' }, applicationRef: { id: application.id, version: 1, sha256: application.sha256 } });
  expect(api.instantiate).not.toHaveBeenCalled();
});

it('retains the goal when read-only matching fails and allows a deliberate retry', async () => {
  vi.mocked(api.matchTemplate).mockRejectedValueOnce(new Error('Synthetic no unique template'));
  await mount('/?tab=templates&templateStart=1');
  await settle(() => expect(host.querySelector('#task-goal')).not.toBeNull()); await input('#task-goal', '校验当前文件');
  await click('匹配任务模板'); await settle(() => expect(host.textContent).toContain('Synthetic no unique template'));
  expect(host.querySelector<HTMLTextAreaElement>('#task-goal')!.value).toBe('校验当前文件');
  await click('匹配任务模板'); await settle(() => expect(host.querySelector('[aria-label="文件路径（必需）"]')).not.toBeNull());
  expect(api.matchTemplate).toHaveBeenCalledTimes(2); expect(api.propose).not.toHaveBeenCalled(); expect(api.instantiate).not.toHaveBeenCalled();
});

it('review regression: browser back from page two detail does not append duplicate cards', async () => {
  const second = { ...application, id: 'qa-next', name: 'QA 第二页' };
  vi.mocked(api.templateCatalog).mockImplementation(async after => after ? { items: [second], nextCursor: null } : { items: [application], nextCursor: 'cursor-1' });
  vi.mocked(api.inspectApplication).mockResolvedValue({ ...version, application: second });
  await mount('/?tab=templates');
  await settle(() => expect(buttons('更多模板')).toHaveLength(1));
  await click('更多模板'); await settle(() => expect(buttons('查看模板')).toHaveLength(2));
  await act(async () => buttons('查看模板')[1]!.click());
  await settle(() => expect(buttons('用此模板创建任务')).toHaveLength(1));
  await act(async () => { history.back(); await new Promise(resolve => setTimeout(resolve, 20)); });
  await settle(() => expect(buttons('查看模板')).toHaveLength(2));
  await act(async () => { history.forward(); await new Promise(resolve => setTimeout(resolve, 20)); });
  await settle(() => expect(buttons('用此模板创建任务')).toHaveLength(1));
  await act(async () => { history.back(); await new Promise(resolve => setTimeout(resolve, 20)); });
  expect(buttons('查看模板')).toHaveLength(2);
  expect(vi.mocked(api.templateCatalog).mock.calls.map(args => args[0])).toEqual([undefined, 'cursor-1']);
});
