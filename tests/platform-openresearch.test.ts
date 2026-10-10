// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { PersonalAgentSessions } from '../web/PersonalAgentSessions.js';
import { applicationEnvironmentApi, type EnvironmentRequest } from '../web/applicationEnvironmentApi.js';
import { ownerModelApi, type OwnerModel } from '../web/ownerModelApi.js';
import { personalAgentApi, PERSONAL_CONTRACT, type PersonalProject } from '../web/personalAgentApi.js';
import { personalRemoteApi } from '../web/personalRemoteApi.js';
import { api } from '../web/api.js';
import type { FactoryJob } from '../web/models.js';

const owner = { id: 'synthetic-owner', name: 'Fixture owner', role: 'user' as const };
const env = { id: 'env-' + 'a'.repeat(32), applicationId: 'openresearch', location: 'platform' as const,
  state: 'ready', packageVersion: 'fixture-package', projectId: 'native-fixture-project',
  connectionRef: 'binding-fixture', modelReference: 'fixture-model', modelRevision: 'one',
  dataRetained: true as const, researchSubmitted: false as const };
const request = (requestId: string): EnvironmentRequest => ({ requestId, action: 'prepare', state: 'ready', diagnostic: null, environment: env });
const project: PersonalProject = { nativeProjectId: env.projectId, namespace: 'native-openresearch',
  upstreamOrxProjectId: env.projectId, executionContract: PERSONAL_CONTRACT, connectionPin: { ref: env.connectionRef },
  modelCredentialCustody: 'owner-vault', budgetEnforcement: 'advisory', stopGuarantee: 'unverified', sessionCreationSupported: true };
let host: HTMLDivElement; let root: Root;
const onModels = vi.fn();
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto);
  localStorage.clear(); sessionStorage.clear(); onModels.mockReset();
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host);
  vi.spyOn(api, 'session').mockResolvedValue(owner); vi.spyOn(api, 'userConnections').mockResolvedValue([]);
  vi.spyOn(personalRemoteApi, 'list').mockResolvedValue([]); vi.spyOn(personalAgentApi, 'sessions').mockResolvedValue([]);
  vi.spyOn(personalAgentApi, 'capabilities').mockResolvedValue({ executionContract: PERSONAL_CONTRACT, nativeQueue: true,
    ownerSubmit: '/api/factory/personal-agent/commands/submit', modelConfiguration: 'remote-configured-model', factoryBYOKForwarded: false });
  vi.spyOn(applicationEnvironmentApi, 'capabilities').mockResolvedValue({ locations: ['platform'], applications: ['openresearch'] });
  vi.spyOn(ownerModelApi, 'list').mockResolvedValue([{ isDefault: true, available: true } as OwnerModel]);
  vi.spyOn(applicationEnvironmentApi, 'prepare').mockImplementation(async (_, id) => request(id));
  vi.spyOn(applicationEnvironmentApi, 'recover').mockImplementation(async id => request(id));
  vi.spyOn(personalAgentApi, 'project').mockResolvedValue(project);
  vi.spyOn(personalAgentApi, 'submit').mockResolvedValue({ id: 'task-fixture', ownerId: owner.id, planId: 'plan-fixture' } as FactoryJob);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount() { await act(async () => root.render(createElement(PersonalAgentSessions, { ownerId: owner.id, namespace: 'native-openresearch', researchJourney: true, onModels }))); }
const button = (label: string) => [...host.querySelectorAll('button')].find(item => item.textContent === label)!;
async function goal(text: string) { await act(async () => { const input = host.querySelector<HTMLTextAreaElement>('[aria-label="研究目标"]')!; Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, text); input.dispatchEvent(new Event('input', { bubbles: true })); }); }

it('prepares on the owner click then submits one existing native create command, with no goal in preparation', async () => {
  await mount(); expect(host.querySelector<HTMLSelectElement>('[aria-label="运行位置"]')!.value).toBe('platform');
  await goal('Synthetic native goal');
  await act(async () => { button('开始研究').click(); button('开始研究').click(); });
  expect(applicationEnvironmentApi.prepare).toHaveBeenCalledTimes(1);
  expect(applicationEnvironmentApi.prepare).toHaveBeenCalledWith(owner.id, expect.any(String));
  expect(personalAgentApi.submit).toHaveBeenCalledTimes(1);
  expect(personalAgentApi.submit).toHaveBeenCalledWith(expect.objectContaining({ action: 'create', nativeProjectId: env.projectId, connectionRef: env.connectionRef }), owner.id);
  expect(personalAgentApi.submit).not.toHaveBeenCalledWith(expect.objectContaining({ action: 'prompt' }), owner.id);
  expect(localStorage.getItem(`factory-environment-prepare:${owner.id}`)).toBeNull();
});

it('reload only reads the original preparation and keeps goal dispatch behind a new click', async () => {
  localStorage.setItem(`factory-environment-prepare:${owner.id}`, 'original-prepare');
  sessionStorage.setItem(`factory-research-draft:${owner.id}`, JSON.stringify({ goal: 'Synthetic retained goal', materials: '' }));
  await mount(); expect(applicationEnvironmentApi.recover).toHaveBeenCalledWith('original-prepare', expect.any(AbortSignal));
  expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.submit).not.toHaveBeenCalled();
  expect(host.querySelector<HTMLTextAreaElement>('[aria-label="研究目标"]')!.value).toBe('Synthetic retained goal');
  await act(async () => button('核对原环境准备').click());
  expect(personalAgentApi.submit).not.toHaveBeenCalled();
});

it('unknown prepare cannot create a session and missing model links to settings', async () => {
  vi.mocked(applicationEnvironmentApi.prepare).mockImplementation(async (_, id) => ({ ...request(id), state: 'unknown', environment: { ...env, state: 'unknown' } }));
  await mount(); await goal('Synthetic retained goal'); await act(async () => button('开始研究').click());
  expect(personalAgentApi.submit).not.toHaveBeenCalled(); expect(host.textContent).toContain('环境准备尚未确认');
  expect(localStorage.getItem(`factory-environment-prepare:${owner.id}`)).toBeTruthy();
  await act(async () => root.unmount()); root = createRoot(host);
  vi.mocked(ownerModelApi.list).mockResolvedValue([]); await mount();
  expect(button('开始研究').disabled).toBe(true);
  await act(async () => button('设置我的模型').click()); expect(onModels).toHaveBeenCalledTimes(1);
});

it('an owner change during prepare prevents the queued native session submission', async () => {
  let finish!: (value: EnvironmentRequest) => void;
  vi.mocked(applicationEnvironmentApi.prepare).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  await mount(); await goal('Synthetic private goal'); await act(async () => button('开始研究').click());
  const id = vi.mocked(applicationEnvironmentApi.prepare).mock.calls[0][1];
  vi.mocked(api.session).mockResolvedValue({ ...owner, id: 'foreign-owner' });
  await act(async () => finish(request(id)));
  expect(personalAgentApi.submit).not.toHaveBeenCalled();
  expect(host.querySelector<HTMLTextAreaElement>('[aria-label="研究目标"]')!.value).toBe('');
});
