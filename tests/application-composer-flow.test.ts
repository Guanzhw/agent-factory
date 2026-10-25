// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApplicationComposer, ComposerProposalScope } from '../web/ApplicationComposer.js';
import { api } from '../web/api.js';
import type { AssemblyCandidate, AssemblyProposal, ExecutionTarget, FactoryApplication, FactoryMaterial, Plan, PlanAuthorization, UserConnection } from '../web/models.js';

const owner = { id: 'alice', name: 'Alice', role: 'user' as const };
const proposalId = '11111111-1111-4111-8111-111111111111';
const applicationRef = { id: 'approved-fixture', version: 1, sha256: 'a'.repeat(64) };
const tool: FactoryMaterial = { id: 'tool-read', version: 1, sha256: 'b'.repeat(64), kind: 'tool', name: '公开来源读取', description: '合成演示', content: 'read_source', license: 'MIT', origin: 'fixture', dependencies: [], compatibility: [], permissions: ['read:public'], inputSchema: {}, outputSchema: {}, archived: false, published: true, createdAt: '2026-10-08T00:00:00Z' };
const toolRef = { id: tool.id, version: tool.version, sha256: tool.sha256 };
const budget = { toolCalls: 8, maxDepth: 2, maxChildren: 4, experimentSeconds: 8, outputBytes: 65536 };
const application: FactoryApplication = { ...applicationRef, name: '公开证据比较', description: '比较来源与差异', discoveryKeywords: ['比较'], defaultForDiscovery: true, defaultMode: 'literature', modes: { literature: { materialRefs: [toolRef], materialChoices: { reader: { kind: 'tool', defaultRef: toolRef, allowedRefs: [toolRef] } }, capabilities: ['read:public'], budget, config: {}, toolOrder: ['read_source'], connectionRequirements: [{ name: 'model', kind: 'model', requiredCapabilities: ['text'], required: true }] } } };
const connection: UserConnection = { ref: 'fixture-connection', ownerId: owner.id, version: 1, fingerprint: 'c'.repeat(64), kind: 'model', revision: 'r1', capabilities: ['text'], taskId: null, registrationRef: 'fixture-model', expiresAt: null, createdAt: '2026-10-08T00:00:00Z', revokedAt: null, status: 'active', available: true, allowedActions: ['inspect', 'revoke'] };
const candidate: AssemblyCandidate = { application: application.id, applicationRef, mode: 'literature', normalizedGoal: '比较两种公开方法', materialRefs: [toolRef], materials: [tool], tools: ['read_source'], capabilities: ['read:public'], budget, config: {}, instructions: 'Bounded fixture', status: 'ready', missing: [], policy: {}, syntheticFixture: true, executionBindings: null, bindingManifest: {}, fingerprint: 'd'.repeat(64) };
const plan: Plan = { id: 'plan-fixture', fingerprint: 'e'.repeat(64), normalizedGoal: candidate.normalizedGoal, applicationRef, materialRefs: [toolRef], capabilities: candidate.capabilities, missing: [], status: 'ready', createdAt: '2026-10-08T00:00:00Z', bindingManifest: { connections: { model: { ref: connection.ref, fingerprint: connection.fingerprint } } } };
const baseAuthorization: PlanAuthorization = { ownerId: owner.id, planId: plan.id, planFingerprint: plan.fingerprint, executionAllowed: true, reviewRequired: false, reviewRequestSupported: false, nativeToolConfirmationRequired: false, policy: { name: 'member-self-service', revision: 'r1', fingerprint: 'f'.repeat(64), review_ttl_seconds: 300, nativeToolConfirmationSeparate: true } };
let host: HTMLDivElement; let root: Root; let saved: AssemblyProposal | undefined; let savedPlan: Plan | null;
let authorization: PlanAuthorization;
let executionTargets: ExecutionTarget[];
let acceptedPlan: Plan;
const onCreated = vi.fn();
function Harness() {
  const [busy, setBusy] = useState(''); const [error, setError] = useState('');
  return createElement('div', null, error && createElement('p', { role: 'alert' }, error), createElement(ApplicationComposer, {
    user: owner, busy, materials: [tool], targets: executionTargets, onCreated,
    act: async (name, work) => { setBusy(name); setError(''); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(''); } },
  }));
}
const button = (text: string) => {
  const found = [...host.querySelectorAll('button')].find(item => item.textContent === text);
  expect(found, `button ${text}`).toBeDefined(); return found!;
};
async function click(text: string) { await act(async () => { button(text).click(); }); }
async function settle(assert: () => void) { await vi.waitFor(async () => { await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); }); assert(); }); }
async function mount() { await act(async () => { root.render(createElement(Harness)); }); await settle(() => expect(host.querySelector<HTMLSelectElement>('#application-selector')?.disabled).toBe(false)); }
async function fillTask() {
  await act(async () => {
    const select = host.querySelector<HTMLSelectElement>('#application-selector')!; select.value = application.id; select.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await act(async () => {
    const goal = host.querySelector<HTMLTextAreaElement>('#task-goal')!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(goal, candidate.normalizedGoal);
    goal.dispatchEvent(new Event('input', { bubbles: true }));
    const select = host.querySelector<HTMLSelectElement>('[aria-label="资源连接 model"]')!; select.value = connection.ref; select.dispatchEvent(new Event('change', { bubbles: true }));
  });
  expect(button('预览任务方案').disabled).toBe(false);
}
async function previewAndAccept() {
  await fillTask(); await click('预览任务方案'); await settle(() => expect(button('确认范围并保存方案').disabled).toBe(false));
  await click('确认范围并保存方案'); await settle(() => expect(host.querySelector('[aria-label="任务提交检查"]')).not.toBeNull());
}
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto);
  window.sessionStorage.clear(); window.localStorage.clear();
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host);
  saved = undefined; savedPlan = null; executionTargets = []; acceptedPlan = plan; authorization = structuredClone(baseAuthorization); onCreated.mockReset();
  vi.spyOn(api, 'session').mockResolvedValue(owner); vi.spyOn(api, 'applications').mockResolvedValue([application]);
  vi.spyOn(api, 'userConnections').mockResolvedValue([connection]);
  vi.spyOn(api, 'proposalInbox').mockResolvedValue({ schema: 1, ownerId: owner.id, snapshot: false, items: [], nextCursor: null });
  vi.spyOn(api, 'propose').mockImplementation(async input => {
    saved = { id: proposalId, ownerId: owner.id, createdAt: '2026-10-08T00:00:00Z', parentId: null, input, candidate: { ...candidate, normalizedGoal: input.goal }, selection: { method: 'explicit-application', matchedKeywords: [] }, fingerprint: '1'.repeat(64), state: 'pending', planId: null, allowedActions: ['revise', 'accept', 'reject'] }; return saved;
  });
  vi.spyOn(api, 'recoverProposal').mockImplementation(async () => { if (!saved) throw new Error('No saved record'); return { proposal: saved, plan: savedPlan }; });
  vi.spyOn(api, 'acceptProposal').mockImplementation(async () => { saved = { ...saved!, state: 'accepted', planId: plan.id, allowedActions: [] }; savedPlan = acceptedPlan; return acceptedPlan; });
  vi.spyOn(api, 'planAuthorization').mockImplementation(async () => authorization);
  vi.spyOn(api, 'planReviews').mockRejectedValue(new Error('Legacy history unavailable'));
  vi.spyOn(api, 'requestPlanReview');
  vi.spyOn(api, 'instantiate').mockResolvedValue({ id: 'created-task' } as Awaited<ReturnType<typeof api.instantiate>>);
});
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('mounted task creation flow', () => {
  it('offers a labeled fresh task before folded history and explains the four steps', async () => {
    await mount();
    const history = [...host.querySelectorAll('details')].find(item => item.querySelector('summary')?.textContent === '继续之前的任务 · 提案与方案历史')!;
    const form = host.querySelector('form')!;
    expect(history.open).toBe(false);
    expect(form.compareDocumentPosition(history) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const goal = host.querySelector<HTMLTextAreaElement>('#task-goal')!;
    expect(host.querySelector('label[for="task-goal"]')?.textContent).toBe('2. 描述任务');
    expect(goal.value).toBe(''); expect(goal.disabled).toBe(false); expect(goal.required).toBe(true);
    expect(button('预览任务方案').disabled).toBe(true);
    const steps = host.querySelector('[aria-label="新建任务步骤"]')!;
    expect([...steps.querySelectorAll('li')].map(item => item.textContent?.replace(/^\d/, ''))).toEqual(['选择应用', '描述任务', '核对方案', '开始任务']);
    expect(steps.querySelector('[aria-current="step"]')?.textContent).toContain('选择应用');
    expect(form.textContent).toContain('不会开始执行');
    expect(api.propose).not.toHaveBeenCalled(); expect(api.instantiate).not.toHaveBeenCalled();
  });
  it.each(['malformed', 'unavailable'])('keeps fresh task entry usable when recovery storage is %s', async condition => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem');
    if (condition === 'malformed') getItem.mockReturnValue('../foreign-record');
    else getItem.mockImplementation(() => { throw new Error('storage unavailable'); });
    await mount();
    expect(host.textContent).not.toContain('继续上次保存的任务');
    expect(host.querySelector<HTMLTextAreaElement>('#task-goal')!.disabled).toBe(false);
    await fillTask();
    expect(button('预览任务方案').disabled).toBe(false);
    expect(api.recoverProposal).not.toHaveBeenCalled(); expect(api.propose).not.toHaveBeenCalled(); expect(api.instantiate).not.toHaveBeenCalled();
  });
  it('shows tools, capabilities, budgets, missing requirements and external inputs before technical disclosure', async () => {
    const external = '<script>example</script>';
    const value: AssemblyCandidate = { ...candidate, status: 'blocked', missing: ['请选择必需的模型连接'],
      config: { internalOption: 'fixture-only' }, executionBindings: { model: { adapterId: 'fixture-model', revision: 'r1' } },
      inputSchema: { type: 'object', properties: { topic: { type: 'string', title: '比较范围', maxLength: 100 } }, additionalProperties: false },
      inputValues: { topic: external } };
    await act(async () => { root.render(createElement(ComposerProposalScope, { candidate: value })); });
    const details = [...host.querySelectorAll('details')].find(item => item.querySelector('summary')?.textContent === '查看材料、适配器与固定配置')!;
    expect(details.open).toBe(false);
    for (const label of ['使用的工具', '能力与权限边界', '固定预算上限', '比较范围']) {
      const term = [...host.querySelectorAll('dt')].find(item => item.textContent === label)!;
      expect(term, label).toBeDefined(); expect(term.closest('details'), label).toBeNull();
    }
    for (const text of ['read_source', 'read:public', '工具调用 8', external]) {
      const entry = [...host.querySelectorAll('dd')].find(item => item.textContent?.includes(text))!;
      expect(entry, text).toBeDefined(); expect(entry.closest('details'), text).toBeNull();
    }
    const missing = host.querySelector('[aria-label="开始前需要补充"]')!;
    expect(missing.textContent).toContain('请选择必需的模型连接'); expect(missing.closest('details')).toBeNull();
    const fixtureNotice = [...host.querySelectorAll('div')].find(item => item.textContent?.includes('不会调用付费模型'))!;
    expect(fixtureNotice.closest('details')).toBeNull();
    expect(host.querySelector('script')).toBeNull();
    expect(host.querySelector('[aria-label="提案固定输入"]')?.textContent).toContain(external);
    details.open = true;
    for (const text of ['六类固定材料', 'fixture-model@r1', 'internalOption', 'fixture-only']) expect(details.textContent).toContain(text);
  });
  it('starts an ordinary application after explicit owner confirmation without administrator decisions', async () => {
    await mount(); expect(api.recoverProposal).not.toHaveBeenCalled();
    await fillTask();
    expect(host.querySelector('[aria-label="资源连接 model"]')!.closest('details')).toBeNull();
    expect(host.querySelector('[aria-label="材料选择 reader"]')?.closest('details')?.open).toBe(false);
    await click('预览任务方案'); await settle(() => expect(button('确认范围并保存方案').disabled).toBe(false));
    expect(api.propose).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.propose).mock.calls[0][0]).toMatchObject({ application: application.id, goal: candidate.normalizedGoal, connectionRefs: { model: connection.ref } });
    expect(api.instantiate).not.toHaveBeenCalled();
    await click('确认范围并保存方案'); await settle(() => expect(button('开始任务').disabled).toBe(false));
    expect(host.textContent).not.toContain('提交方案审查'); expect(api.planReviews).not.toHaveBeenCalled(); expect(api.requestPlanReview).not.toHaveBeenCalled();
    expect(api.instantiate).not.toHaveBeenCalled();
    await click('开始任务'); await settle(() => expect(onCreated).toHaveBeenCalledWith('created-task'));
    expect(api.instantiate).toHaveBeenCalledTimes(1); expect(vi.mocked(api.instantiate).mock.calls[0][0]).toBe(plan.id);
  });
  it('keeps a legacy denied or unknown plan disabled without automatic instantiation', async () => {
    authorization = { ...baseAuthorization, executionAllowed: false, code: 'LEGACY_PLAN_READ_ONLY', message: '历史方案只读，请重新生成。' };
    await mount(); await previewAndAccept();
    expect(button('开始任务').disabled).toBe(true); expect(host.textContent).toContain('历史方案只读');
    authorization = { ...baseAuthorization, executionAllowed: false, code: 'ADMISSION_UNKNOWN', message: '原请求结果未知，请核对原任务。' };
    await click('刷新提交状态'); await settle(() => expect(host.textContent).toContain('原请求结果未知'));
    expect(button('开始任务').disabled).toBe(true); await click('开始任务'); expect(api.instantiate).not.toHaveBeenCalled();
    expect(api.requestPlanReview).not.toHaveBeenCalled();
  });
  it('explains an empty application catalog and cannot submit a task', async () => {
    vi.mocked(api.applications).mockResolvedValue([]); await mount();
    expect(host.textContent).toContain('当前没有可用的已发布应用');
    expect(button('预览任务方案').disabled).toBe(true); await click('预览任务方案');
    expect(api.propose).not.toHaveBeenCalled(); expect(api.instantiate).not.toHaveBeenCalled();
  });
  it('requires explicit historical recovery and refuses a foreign owner while preserving fresh input', async () => {
    window.sessionStorage.setItem('factory-proposal-v1:alice', proposalId);
    vi.mocked(api.recoverProposal).mockResolvedValue({ proposal: { id: proposalId, ownerId: 'bob' } as AssemblyProposal, plan });
    await mount(); await fillTask(); expect(api.recoverProposal).not.toHaveBeenCalled();
    const history = button('继续上次保存的任务').closest('details')!;
    expect(history.open).toBe(false);
    await act(async () => { history.open = true; });
    await click('继续上次保存的任务'); await settle(() => expect(host.textContent).toContain('提案归属或修订范围无法核对'));
    expect(host.querySelector<HTMLTextAreaElement>('#task-goal')!.value).toBe(candidate.normalizedGoal);
    expect(host.querySelector('[aria-label="任务提交检查"]')).toBeNull();
    expect(window.sessionStorage.getItem('factory-proposal-v1:alice')).toBe(proposalId);
    expect(api.recoverProposal).toHaveBeenCalledExactlyOnceWith(proposalId);
    expect(api.propose).not.toHaveBeenCalled(); expect(api.acceptProposal).not.toHaveBeenCalled(); expect(api.instantiate).not.toHaveBeenCalled();
  });
  it('locks an uncertain proposal request and retries with the same input and idempotency key', async () => {
    vi.mocked(api.propose).mockRejectedValueOnce(new Error('Synthetic lost acknowledgement'));
    window.sessionStorage.setItem('factory-proposal-v1:alice', proposalId);
    await mount(); await fillTask(); await click('预览任务方案');
    await settle(() => expect(host.textContent).toContain('原装配请求未确认'));
    expect(host.querySelector<HTMLTextAreaElement>('#task-goal')!.disabled).toBe(true);
    expect(button('继续上次保存的任务').disabled).toBe(true);
    const firstCall = vi.mocked(api.propose).mock.calls[0];
    await click('核对原装配请求'); await settle(() => expect(button('确认范围并保存方案').disabled).toBe(false));
    expect(vi.mocked(api.propose).mock.calls[1]).toEqual(firstCall);
    expect(api.instantiate).not.toHaveBeenCalled();
  });
  it('can reconcile an uncertain request after the application catalog becomes empty using the original body and key', async () => {
    vi.mocked(api.propose).mockRejectedValueOnce(new Error('Synthetic lost acknowledgement'));
    await mount(); await fillTask(); await click('预览任务方案');
    await settle(() => expect(host.textContent).toContain('原装配请求未确认'));
    const originalCall = structuredClone(vi.mocked(api.propose).mock.calls[0]);
    vi.mocked(api.applications).mockResolvedValue([]);
    // Let the existing read-only refresh observe the now-empty catalog.
    await vi.waitFor(async () => {
      await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
      expect(host.textContent).toContain('当前没有可用的已发布应用');
    }, { timeout: 7000, interval: 50 });
    expect(host.querySelector<HTMLTextAreaElement>('#task-goal')!.disabled).toBe(true);
    expect(button('核对原装配请求').disabled).toBe(false);
    await click('核对原装配请求'); await settle(() => expect(button('确认范围并保存方案').disabled).toBe(false));
    expect(api.propose).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.propose).mock.calls[1]).toEqual(originalCall);
    expect(api.instantiate).not.toHaveBeenCalled();
  });

});


describe('declared remote application contracts', () => {
  const remote = { id: 'remote-fixture', name: 'Synthetic receiver', kind: 'remote-factory' as const, connectivityVerified: false };
  async function selectTarget(id: string) {
    await act(async () => {
      const select = host.querySelector<HTMLSelectElement>('[aria-label="执行位置"]')!;
      select.value = id; select.dispatchEvent(new Event('change', { bubbles: true }));
    });
  }
  async function readyPlan(version?: 1 | 2) {
    acceptedPlan = { ...plan, ...(version ? { contractVersion: version } : {}) };
    await mount(); await previewAndAccept();
    await settle(() => expect(button('开始任务').disabled).toBe(false));
  }
  it.each([undefined, 1] as const)('preserves omitted/default target v1 support for plan version %s', async version => {
    executionTargets = [remote];
    await readyPlan(version);
    const option = host.querySelector<HTMLOptionElement>('option[value="remote-fixture"]')!;
    expect(option.disabled).toBe(false);
    expect(option.textContent).toContain('声明契约 v1');
    await selectTarget(remote.id);
    expect(host.textContent).toContain('连接未验证');
    expect(host.textContent).not.toContain('连接已验证');
    await click('开始任务');
    await settle(() => expect(api.instantiate).toHaveBeenCalledWith(plan.id, expect.any(String), remote.id));
  });
  it('disables a v1-only receiver for an immutable v2 plan and guards submission without downgrade', async () => {
    executionTargets = [remote];
    await readyPlan(2);
    expect(host.querySelector<HTMLOptionElement>('option[value="remote-fixture"]')!.disabled).toBe(true);
    expect(host.textContent).toContain('不支持当前 v2');
    // A synthetic change event cannot turn a disabled option into permission to submit.
    await selectTarget(remote.id);
    expect(button('开始任务').disabled).toBe(true);
    expect(host.textContent).toContain('所选目标未声明支持方案契约 v2');
    await click('开始任务');
    expect(api.instantiate).not.toHaveBeenCalled();
    expect(acceptedPlan.contractVersion).toBe(2);
    expect(host.querySelector<HTMLSelectElement>('[aria-label="执行位置"]')!.value).toBe(remote.id);
  });
  it('uses explicit v2 support without treating declaration or connectivity as execution proof', async () => {
    executionTargets = [{ ...remote, supportedApplicationContracts: [1, 2] }];
    await readyPlan(2);
    expect(host.querySelector<HTMLOptionElement>('option[value="remote-fixture"]')!.disabled).toBe(false);
    await selectTarget(remote.id);
    expect(host.textContent).toContain('声明契约 v1、v2');
    expect(host.textContent).toContain('连接未验证');
    expect(host.textContent).toContain('目标版本为静态声明');
    await click('开始任务');
    await settle(() => expect(api.instantiate).toHaveBeenCalledWith(plan.id, expect.any(String), remote.id));
  });
  it('retains the selected receiver and blocks starting when its declared version disappears', async () => {
    executionTargets = [{ ...remote, connectivityVerified: true, supportedApplicationContracts: [1, 2] }];
    await readyPlan(2); await selectTarget(remote.id);
    expect(host.textContent).toContain('连接已验证');
    expect(host.textContent).toContain('连接验证不代表任务可执行');
    executionTargets = [{ ...remote, connectivityVerified: true, supportedApplicationContracts: [1] }];
    await act(async () => root.render(createElement(Harness)));
    expect(host.querySelector<HTMLSelectElement>('[aria-label="执行位置"]')!.value).toBe(remote.id);
    expect(button('开始任务').disabled).toBe(true);
    await click('开始任务'); expect(api.instantiate).not.toHaveBeenCalled();
    executionTargets = [];
    await act(async () => root.render(createElement(Harness)));
    expect(host.querySelector<HTMLSelectElement>('[aria-label="执行位置"]')!.value).toBe(remote.id);
    expect(host.textContent).toContain('所选目标当前不可用');
    expect(button('开始任务').disabled).toBe(true);
    await selectTarget('');
    expect(button('开始任务').disabled).toBe(false);
    expect(api.instantiate).not.toHaveBeenCalled();
  });
});
