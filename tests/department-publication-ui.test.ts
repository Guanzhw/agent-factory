// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApplicationGovernance } from '../web/ApplicationGovernance.js';
import { MaterialGovernancePanel } from '../web/MaterialGovernance.js';
import { PlanReviews } from '../web/PlanReviews.js';
import { api } from '../web/api.js';
import { publicationApi } from '../web/publicationApi.js';
import type { ApplicationVersion, FactoryApplication, FactoryMaterial, PlanReview, User } from '../web/models.js';

const member: User = { id: 'alice', name: 'Alice', role: 'user' };
const manager: User = { id: 'manager', name: 'Manager', role: 'manager' };
const application: FactoryApplication = { id: 'department-not-a-whitelist-app', version: 2, sha256: 'a'.repeat(64), name: '共享工作流', description: '合成应用', discoveryKeywords: [], defaultForDiscovery: false, defaultMode: 'work', modes: { work: { materialRefs: [], materialChoices: {}, capabilities: [], budget: { toolCalls: 1, maxDepth: 1, maxChildren: 1, outputBytes: 1024 }, config: {}, toolOrder: [], connectionRequirements: [] } } };
const version: ApplicationVersion = { application, governance: { author_id: member.id, state: 'draft', bootstrap: false, review_id: null, reason: null }, immutableBodyPreserved: true };
const material: FactoryMaterial = { id: 'department-material', version: 2, sha256: 'b'.repeat(64), kind: 'prompt', name: '共享提示词', description: '合成材料', content: 'synthetic', license: 'MIT', origin: 'fixture', dependencies: [], compatibility: ['agno:3.1.0'], permissions: [], inputSchema: {}, outputSchema: {}, archived: false, published: false, createdAt: '2026-10-13T00:00:00Z', governance: { state: 'draft', authorId: member.id } };
const history: PlanReview = { id: 'old-review', ownerId: member.id, planId: 'old-plan', planDigest: 'c'.repeat(64), planFingerprint: 'd'.repeat(64), policyRevision: 'old', expiresAt: '2026-10-01T00:00:00Z', expired: true, currentPolicy: false, planIntegrityMatches: true, decision: 'pending', approvalEffective: false, reviewerId: null, planSummary: {}, ...{ policyDigest: 'e'.repeat(64), requestId: 'old-request', createdAt: '2026-09-30T00:00:00Z' } };
let host: HTMLDivElement; let root: Root; let listedMaterials: FactoryMaterial[]; const notice = vi.fn();
function Harness({ page, user }: { page: 'applications' | 'materials' | 'history'; user: User }) {
  const [busy, setBusy] = useState(''); const [error, setError] = useState('');
  const run = async (name: string, work: () => Promise<void>) => { setBusy(name); setError(''); try { await work(); } catch (e) { setError(String(e)); } finally { setBusy(''); } };
  return createElement('div', null, error && createElement('p', { role: 'alert' }, error), page === 'applications'
    ? createElement(ApplicationGovernance, { user, materials: listedMaterials, busy, act: run, onNotice: notice })
    : page === 'materials' ? createElement(MaterialGovernancePanel, { user, materials: listedMaterials, busy, act: run, onNotice: notice })
    : createElement(PlanReviews, { ownerId: user.id, busy, act: run }));
}
const button = (text: string) => [...host.querySelectorAll('button')].find(item => item.textContent === text);
async function click(text: string) { expect(button(text)).toBeDefined(); await act(async () => button(text)!.click()); }
async function settle(check: () => void) { await vi.waitFor(async () => { await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); }); check(); }); }
async function mount(page: 'applications' | 'materials' | 'history', user = member) { vi.mocked(api.session).mockResolvedValue(user); await act(async () => root.render(createElement(Harness, { page, user }))); }
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto); sessionStorage.clear(); notice.mockReset();
  listedMaterials = [material];
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  vi.spyOn(api, 'session').mockResolvedValue(member);
  vi.spyOn(api, 'applicationVersions').mockResolvedValue([version]); vi.spyOn(api, 'applications').mockResolvedValue([]);
  vi.spyOn(api, 'applicationReviews').mockRejectedValue(new Error('old review service unavailable'));
  vi.spyOn(api, 'materialReviews').mockRejectedValue(new Error('old review service unavailable'));
  vi.spyOn(api, 'materialPolicy').mockRejectedValue(new Error('old review policy unavailable'));
  vi.spyOn(api, 'requestApplicationPublication'); vi.spyOn(api, 'decideApplicationReview');
  vi.spyOn(api, 'requestMaterialPublication'); vi.spyOn(api, 'decideMaterialReview');
  vi.spyOn(publicationApi, 'publishApplication').mockResolvedValue(application);
  const { governance: _governance, ...materialBody } = material;
  void _governance;
  vi.spyOn(publicationApi, 'publishMaterial').mockResolvedValue({ ...materialBody, published: true });
  vi.spyOn(api, 'archiveApplication').mockResolvedValue({}); vi.spyOn(api, 'withdrawApplication').mockResolvedValue({});
  vi.spyOn(api, 'archiveMaterial').mockResolvedValue({}); vi.spyOn(api, 'withdrawMaterial').mockResolvedValue({});
  vi.spyOn(api, 'planReviews').mockResolvedValue([history]); vi.spyOn(api, 'decidePlanReview');
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('lets a member publish an exact application version without loading legacy reviews', async () => {
  await mount('applications'); expect(button('发布此版本')?.disabled).toBe(false);
  expect(button('撤回此版本')).toBeUndefined(); expect(button('归档此版本')).toBeDefined();
  expect(api.applicationVersions).toHaveBeenCalledWith(true, expect.any(AbortSignal)); expect(api.applicationReviews).not.toHaveBeenCalled();
  await click('发布此版本'); await settle(() => expect(notice).toHaveBeenCalled()); expect(publicationApi.publishApplication).toHaveBeenCalledWith(member.id, application.id, 2, expect.any(String));
  expect(notice).toHaveBeenCalledWith(expect.stringContaining('已有任务继续保留原固定版本与个人绑定'));
  expect(api.requestApplicationPublication).not.toHaveBeenCalled(); expect(api.decideApplicationReview).not.toHaveBeenCalled();
});
it('lets a member publish an exact material version while legacy review APIs are unavailable', async () => {
  await mount('materials'); expect(button('新建材料')?.disabled).toBe(false); expect(button('发布此版本')?.disabled).toBe(false);
  expect(button('撤回此版本')).toBeUndefined(); expect(button('归档此版本')).toBeDefined();
  expect(api.materialPolicy).not.toHaveBeenCalled(); expect(api.materialReviews).not.toHaveBeenCalled();
  await click('发布此版本'); await settle(() => expect(notice).toHaveBeenCalled()); expect(publicationApi.publishMaterial).toHaveBeenCalledWith(member.id, material.id, 2, expect.any(String));
  expect(notice).toHaveBeenCalledWith(expect.stringContaining('已有任务继续保留原固定版本'));
  expect(api.requestMaterialPublication).not.toHaveBeenCalled(); expect(api.decideMaterialReview).not.toHaveBeenCalled();
});
it('retains the exact publication idempotency key after an unknown reply', async () => {
  vi.mocked(publicationApi.publishApplication).mockRejectedValueOnce(new Error('UNKNOWN synthetic lost reply'));
  await mount('applications'); await click('发布此版本'); await settle(() => expect(host.textContent).toContain('UNKNOWN'));
  const original = vi.mocked(publicationApi.publishApplication).mock.calls[0]; expect(notice).not.toHaveBeenCalled();
  await click('发布此版本'); await settle(() => expect(notice).toHaveBeenCalled()); expect(vi.mocked(publicationApi.publishApplication).mock.calls[1]).toEqual(original);
  expect(publicationApi.publishApplication).toHaveBeenCalledTimes(2);
});
it('shows public retirement controls only to an administrator and preserves version history wording', async () => {
  vi.mocked(api.applicationVersions).mockResolvedValue([{ ...version, governance: { ...version.governance, state: 'published' } }]);
  await mount('applications', manager); expect(button('撤回此版本')).toBeDefined(); expect(button('归档此版本')).toBeDefined();
  expect(host.textContent).toContain('历史保留'); expect(button('发布此版本')).toBeUndefined();
});
it('does not offer publication of another member draft', async () => {
  vi.mocked(api.applicationVersions).mockResolvedValue([{ ...version, governance: { ...version.governance, author_id: 'bob' } }]);
  await mount('applications', manager); expect(button('发布此版本')).toBeUndefined();
});
it('shows old pending plan evidence without decisions, polling, or dispatch', async () => {
  vi.useFakeTimers();
  try {
    await mount('history', manager); expect(host.textContent).toContain('历史待审查');
    expect(button('同意方案')).toBeUndefined(); expect(button('拒绝方案')).toBeUndefined();
    await act(async () => vi.advanceTimersByTimeAsync(15000));
    expect(api.planReviews).toHaveBeenCalledTimes(1); expect(api.decidePlanReview).not.toHaveBeenCalled();
  } finally { vi.useRealTimers(); }
});

it('reads old material evidence when task approval is no longer a separate requirement', async () => {
  vi.mocked(api.materialReviews).mockResolvedValue([{ id: 'old-material-review', authorId: member.id, requestedBy: member.id, materialId: material.id, version: material.version, createdAt: '2026-10-01T00:00:00Z', policyRevision: 'old', sha256: material.sha256, immutableDigest: 'f'.repeat(64), currentPolicy: false, demoCompatibility: false, taskApprovalSeparate: false, decision: 'pending', state: 'draft', material }]);
  await mount('materials'); await click('读取历史记录');
  expect(host.textContent).toContain('等待审核'); expect(host.querySelector('[role="alert"]')).toBeNull();
  expect(button('同意发布此版本')).toBeUndefined(); expect(button('拒绝发布')).toBeUndefined();
  expect(publicationApi.publishMaterial).not.toHaveBeenCalled(); expect(api.decideMaterialReview).not.toHaveBeenCalled();
});

async function setReason(page: 'applications' | 'materials', reason: string) {
  const selector = page === 'applications' ? '[aria-label="应用归档撤回原因"]' : '[aria-label="确认材料状态变更"] textarea';
  const textarea = host.querySelector<HTMLTextAreaElement>(selector);
  expect(textarea).not.toBeNull();
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(textarea, reason);
    textarea!.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
it.each(['applications', 'materials'] as const)('lets a member archive their private %s draft with a reason while preserving history', async page => {
  await mount(page); expect(button('归档此版本')).toBeDefined(); expect(button('撤回此版本')).toBeUndefined();
  if (page === 'applications') {
    expect(button('归档此版本')!.disabled).toBe(true);
    expect(host.textContent).toContain('私人草稿归档原因');
  } else {
    await click('归档此版本'); expect(host.querySelector('[aria-label="确认材料状态变更"]')).not.toBeNull();
    expect(host.querySelector<HTMLTextAreaElement>('[aria-label="确认材料状态变更"] textarea')!.required).toBe(true);
  }
  await setReason(page, '合成草稿已不再需要');
  await click(page === 'applications' ? '归档此版本' : '确认归档此版本');
  await settle(() => expect(notice).toHaveBeenCalledWith(expect.stringContaining('保留')));
  const archive = page === 'applications' ? api.archiveApplication : api.archiveMaterial;
  expect(archive).toHaveBeenCalledWith(page === 'applications' ? application.id : material.id, 2, '合成草稿已不再需要', expect.any(String));
  expect(api.withdrawApplication).not.toHaveBeenCalled(); expect(api.withdrawMaterial).not.toHaveBeenCalled();
});
it.each(['applications', 'materials'] as const)('does not offer another member private %s draft for archival', async page => {
  vi.mocked(api.applicationVersions).mockResolvedValue([{ ...version, governance: { ...version.governance, author_id: 'bob' } }]);
  listedMaterials = [{ ...material, governance: { ...material.governance!, authorId: 'bob' } }];
  await mount(page);
  expect(button('归档此版本')).toBeUndefined(); expect(button('撤回此版本')).toBeUndefined();
  expect(api.archiveApplication).not.toHaveBeenCalled(); expect(api.archiveMaterial).not.toHaveBeenCalled();
});
it.each([
  ['applications', 'published'], ['applications', 'withdrawn'], ['materials', 'published'], ['materials', 'withdrawn'],
] as const)('does not grant the author destructive %s controls after a version is %s', async (page, state) => {
  vi.mocked(api.applicationVersions).mockResolvedValue([{ ...version, governance: { ...version.governance, state } }]);
  listedMaterials = [{ ...material, published: state === 'published', governance: { ...material.governance!, state } }];
  await mount(page);
  expect(button('归档此版本')).toBeUndefined(); expect(button('撤回此版本')).toBeUndefined();
  expect(host.textContent).toContain('公共版本的撤回和归档由管理员操作');
  expect(api.archiveApplication).not.toHaveBeenCalled(); expect(api.archiveMaterial).not.toHaveBeenCalled();
});
it.each(['applications', 'materials'] as const)('rechecks the signed-in owner before archiving a private %s draft', async page => {
  await mount(page);
  if (page === 'materials') await click('归档此版本');
  await setReason(page, '合成归档原因');
  vi.mocked(api.session).mockResolvedValue({ ...member, id: 'bob' });
  await click(page === 'applications' ? '归档此版本' : '确认归档此版本');
  await settle(() => expect(host.textContent).toContain('当前身份或操作权限无法核对'));
  expect(api.archiveApplication).not.toHaveBeenCalled(); expect(api.archiveMaterial).not.toHaveBeenCalled();
});
