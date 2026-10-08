// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { OpenResearchWorkspace } from '../web/OpenResearchWorkspace.js';
import { api, ApiError } from '../web/api.js';
import { openresearchApi, researchProject, researchSession, type ResearchProject, type ResearchSession } from '../web/openresearchApi.js';
import type { UserConnection } from '../web/models.js';
const hash = 'a'.repeat(64);
const owner = { id: 'alice', name: 'Alice', role: 'user' as const };
const native = { id: 'native-1', name: '真实来源项目', projectIdentityHash: hash, verificationStatus: 'metadata-observed', evidenceKind: 'native-project-metadata' };
const project: ResearchProject = { id: 'orp-one', name: native.name, description: '', kind: 'native-openresearch', upstreamProjectId: native.id, nativeProject: native, connectionRefs: { workspace: 'orx-alice' }, sessionExecutionAvailable: false, sessionBlocker: 'NATIVE_PROJECT_GOVERNED_SESSION_BINDING_REQUIRED' };
const group: ResearchProject = { id: 'orp-group', name: '受控分组', description: '', kind: 'factory-workspace', connectionRefs: {}, upstreamProjectId: null };
const session: ResearchSession = { id: 'ors-one', projectId: group.id, goal: '受控目标', workloadPresetId: 'preset-one', state: 'unknown', taskId: null, executionContract: 'controlled-workload-v1', contextSource: 'approved-workload-preset', verificationStatus: 'not-live-verified' };
const connection: UserConnection = { ref: 'orx-alice', ownerId: 'alice', kind: 'orx', status: 'active', available: true, taskId: null, capabilities: ['project:read'], revision: 'one', version: 1, fingerprint: hash, registrationRef: 'installed-orx', expiresAt: null, revokedAt: null, createdAt: '', allowedActions: ['inspect'] };
let host: HTMLDivElement; let root: Root;
const onTask = vi.fn();
const find = (label: string) => [...host.querySelectorAll('button')].find(b => b.textContent === label)!;
async function click(label: string) { expect(find(label)).toBeTruthy(); await act(async () => find(label).click()); }
async function mount() { await act(async () => root.render(createElement(OpenResearchWorkspace, { ownerId: 'alice', onTask, onResources: vi.fn(), onCatalog: vi.fn() }))); }
async function input(label: string, value: string) { await act(async () => { const el = host.querySelector<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(`[aria-label="${label}"]`)!; const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, value); el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); }); }
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto); localStorage.clear(); onTask.mockReset();
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host);
  vi.spyOn(api, 'session').mockResolvedValue(owner); vi.spyOn(api, 'userConnections').mockResolvedValue([connection]);
  vi.spyOn(openresearchApi, 'capabilities').mockResolvedValue({ contractVersion: 1, nativeProjectAttachment: true, upstreamProjectCreation: false, liveEndToEndVerified: false, workloads: [{ id: 'preset-one', name: '受控预设', ready: true, blockers: [], limits: { maxExperiments: 1 } }] });
  vi.spyOn(openresearchApi, 'projects').mockResolvedValue([]); vi.spyOn(openresearchApi, 'project').mockImplementation(async id => id === group.id ? group : project);
  vi.spyOn(openresearchApi, 'native').mockResolvedValue([native]); vi.spyOn(openresearchApi, 'attach').mockResolvedValue(project); vi.spyOn(openresearchApi, 'refresh').mockResolvedValue(project);
  vi.spyOn(openresearchApi, 'sessions').mockResolvedValue([]); vi.spyOn(openresearchApi, 'start').mockResolvedValue(session); vi.spyOn(openresearchApi, 'create').mockResolvedValue(group);
  vi.spyOn(openresearchApi, 'reconcile').mockResolvedValue(session); vi.spyOn(openresearchApi, 'recover').mockResolvedValue({ session });
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it('reads actual owner resources, attaches exact identity, refreshes native metadata, never substitutes a preset', async () => {
  await mount(); expect(host.querySelector('#application-selector')).toBeNull();
  expect(host.querySelector('input[placeholder*="path"]')).toBeNull();
  await input('我的 OpenResearch 连接', connection.ref); await click('读取原生项目'); await click('关联此项目');
  expect(openresearchApi.attach).toHaveBeenCalledWith(connection.ref, native, expect.any(String));
  expect(host.textContent).toContain('NATIVE_PROJECT_GOVERNED_SESSION_BINDING_REQUIRED');
  expect(find('原生会话不可用').disabled).toBe(true);
  expect(host.querySelector('[aria-label="已批准工作负载"]')).toBeNull();
  await click('刷新原项目元数据'); expect(openresearchApi.refresh).toHaveBeenCalledWith(project.id);
  expect(openresearchApi.start).not.toHaveBeenCalled();
});
it('does not invent usable connections for unconfigured, foreign-owner, revoked or environment resources', async () => {
  vi.mocked(api.userConnections).mockResolvedValue([{ ...connection, kind: 'environment' }, { ...connection, ref: 'revoked', status: 'revoked', available: false }]);
  await mount(); expect(find('读取原生项目').disabled).toBe(true); expect(host.textContent).toContain('尚未配置可用的原生工作区连接');
  await act(async () => root.unmount()); root = createRoot(host); vi.mocked(api.userConnections).mockResolvedValue([{ ...connection, ownerId: 'bob' }]); await mount();
  expect(find('读取原生项目').disabled).toBe(true); expect(host.querySelectorAll('option')).toHaveLength(1);
});
it('persists an interrupted original request, suppresses repeated submissions, and only performs request lookup on recovery', async () => {
  vi.mocked(openresearchApi.projects).mockResolvedValue([group]);
  vi.mocked(openresearchApi.start).mockRejectedValue(new ApiError('lost reply', 0, 'OFFLINE'));
  await mount(); await act(async () => host.querySelector<HTMLButtonElement>('.or-project-card')!.click());
  await input('已批准工作负载', 'preset-one'); await input('研究目标', '受控目标');
  await act(async () => { find('确认范围并提交受控会话').click(); find('确认范围并提交受控会话').click(); });
  expect(openresearchApi.start).toHaveBeenCalledTimes(1);
  const original = vi.mocked(openresearchApi.start).mock.calls[0][3]; expect(localStorage.getItem('factory-or-pending:alice')).toBe(original);
  await act(async () => root.unmount()); root = createRoot(host); await mount();
  expect(host.textContent).toContain(original); expect(openresearchApi.start).toHaveBeenCalledTimes(1);
  vi.mocked(openresearchApi.sessions).mockResolvedValue([session]);
  await click('核对原请求'); expect(openresearchApi.recover).toHaveBeenCalledWith(original);
  expect(host.textContent).toContain('存在未核实准入的原会话'); expect(find('确认范围并提交受控会话').disabled).toBe(true);
  await click('核对原会话'); expect(openresearchApi.reconcile).toHaveBeenCalledWith(group.id, session.id);
  expect(openresearchApi.start).toHaveBeenCalledTimes(1);
});
it('routes results and cancellation to the original task and preserves unknown as unknown', async () => {
  vi.mocked(openresearchApi.projects).mockResolvedValue([group]); vi.mocked(openresearchApi.sessions).mockResolvedValue([{ ...session, taskId: 'original-task', state: 'running' }]);
  await mount(); await act(async () => host.querySelector<HTMLButtonElement>('.or-project-card')!.click());
  await click('任务、证据与取消'); expect(onTask).toHaveBeenCalledWith('original-task'); expect(host.textContent).toContain('not-live-verified');
  expect(openresearchApi.start).not.toHaveBeenCalled();
});
it('rejects wrong identities, malformed session results and native/factory boundary confusion', () => {
  expect(() => researchProject({ ...project, upstreamProjectId: 'different' })).toThrow();
  expect(() => researchProject({ ...group, upstreamProjectId: 'pretend-native' })).toThrow();
  expect(() => researchSession(session, 'other-project')).toThrow();
  expect(() => researchSession({ ...session, contextSource: 'native-project' }, group.id)).toThrow();
});
it('restores an original project pointer through read-only APIs without a new attach or admission', async () => {
  await act(async () => root.render(createElement(OpenResearchWorkspace, { ownerId: 'alice', selectedProject: project.id, onProject: vi.fn(), onTask, onResources: vi.fn(), onCatalog: vi.fn() })));
  expect(openresearchApi.project).toHaveBeenCalledWith(project.id, expect.any(AbortSignal));
  expect(host.textContent).toContain('NATIVE_PROJECT_GOVERNED_SESSION_BINDING_REQUIRED');
  expect(openresearchApi.attach).not.toHaveBeenCalled(); expect(openresearchApi.start).not.toHaveBeenCalled();
});
it('keeps an absent request lookup unresolved and does not infer permission to resend', async () => {
  localStorage.setItem('factory-or-pending:alice', 'original-unknown-request');
  vi.mocked(openresearchApi.recover).mockRejectedValue(new ApiError('absent', 404));
  await mount(); await click('核对原请求'); await click('刷新工作区');
  expect(localStorage.getItem('factory-or-pending:alice')).toBe('original-unknown-request');
  expect(openresearchApi.start).not.toHaveBeenCalled(); expect(openresearchApi.create).not.toHaveBeenCalled(); expect(openresearchApi.attach).not.toHaveBeenCalled();
});
