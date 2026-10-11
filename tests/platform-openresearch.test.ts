// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { PersonalAgentSessions } from '../web/PersonalAgentSessions.js';
import { applicationEnvironmentApi, type EnvironmentRequest } from '../web/applicationEnvironmentApi.js';
import { ownerModelApi, type OwnerModel } from '../web/ownerModelApi.js';
import { personalAgentApi, PERSONAL_CONTRACT, type PersonalProject, type PersonalSession } from '../web/personalAgentApi.js';
import { personalRemoteApi } from '../web/personalRemoteApi.js';
import { api, ApiError } from '../web/api.js';
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
  vi.spyOn(applicationEnvironmentApi, 'list').mockResolvedValue([]);
  vi.spyOn(applicationEnvironmentApi, 'inspect').mockResolvedValue(env);
  vi.spyOn(ownerModelApi, 'list').mockResolvedValue([{ isDefault: true, available: true } as OwnerModel]);
  vi.spyOn(applicationEnvironmentApi, 'prepare').mockImplementation(async (_, id) => request(id));
  vi.spyOn(applicationEnvironmentApi, 'recover').mockImplementation(async id => request(id));
  vi.spyOn(personalAgentApi, 'project').mockResolvedValue(project);
  vi.spyOn(personalAgentApi, 'submit').mockResolvedValue({ id: 'task-fixture', ownerId: owner.id, planId: 'plan-fixture' } as FactoryJob);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount() { await act(async () => root.render(createElement(PersonalAgentSessions, { ownerId: owner.id, namespace: 'native-openresearch', researchJourney: true, onModels }))); }
const button = (label: string) => [...host.querySelectorAll('button')].find(item => item.textContent === label)!;
async function goal(text: string) { await act(async () => { const input = host.querySelector<HTMLTextAreaElement>('[aria-label="研究目标"], [aria-label="继续研究"]')!; Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, text); input.dispatchEvent(new Event('input', { bubbles: true })); }); }

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
  expect(host.querySelector<HTMLTextAreaElement>('[aria-label="研究目标"], [aria-label="继续研究"]')!.value).toBe('Synthetic retained goal');
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
  expect(host.querySelector<HTMLTextAreaElement>('[aria-label="研究目标"], [aria-label="继续研究"]')!.value).toBe('');
});

it('selects an owned Linux server and directory, then uses the existing ordinary native command path', async () => {
  vi.mocked(applicationEnvironmentApi.capabilities).mockResolvedValue({ locations: ['ssh'], applications: ['openresearch'] });
  vi.spyOn(applicationEnvironmentApi, 'servers').mockResolvedValue([{ reference: 'owned-linux', name: 'My Linux', defaultDirectory: '/private/alice/research' }]);
  vi.mocked(applicationEnvironmentApi.prepare).mockImplementation(async (_, id) => ({ ...request(id), environment: {
    ...env, location: 'ssh', serverRef: 'owned-linux', remoteDirectory: '/private/alice/research',
  } }));
  await mount();
  expect(host.querySelector<HTMLSelectElement>('[aria-label="运行位置"]')!.value).toBe('ssh');
  expect(host.querySelector<HTMLSelectElement>('[aria-label="我的服务器"]')!.value).toBe('owned-linux');
  expect(host.querySelector<HTMLInputElement>('[aria-label="研究数据目录"]')!.value).toBe('/private/alice/research');
  await goal('Synthetic SSH goal'); await act(async () => button('开始研究').click());
  expect(applicationEnvironmentApi.prepare).toHaveBeenCalledWith(owner.id, expect.any(String), {
    location: 'ssh', serverRef: 'owned-linux', directory: '/private/alice/research',
  });
  expect(personalAgentApi.submit).toHaveBeenCalledTimes(1);
  expect(personalAgentApi.submit).toHaveBeenCalledWith(expect.objectContaining({ action: 'create', nativeProjectId: env.projectId }), owner.id);
});

it('recovers the original SSH selection after reload without installing or submitting a goal', async () => {
  localStorage.setItem(`factory-environment-prepare:${owner.id}`, 'ssh-unknown-request');
  vi.mocked(applicationEnvironmentApi.capabilities).mockResolvedValue({ locations: ['platform', 'ssh'], applications: ['openresearch'] });
  vi.spyOn(applicationEnvironmentApi, 'servers').mockResolvedValue([{ reference: 'other-linux', name: 'Other Linux', defaultDirectory: '/private/other' }]);
  vi.mocked(applicationEnvironmentApi.recover).mockImplementation(async id => ({ ...request(id), state: 'unknown', environment: {
    ...env, location: 'ssh', state: 'unknown', serverRef: 'original-linux', remoteDirectory: '/private/original',
  } }));
  await mount();
  expect(host.querySelector<HTMLSelectElement>('[aria-label="运行位置"]')!.value).toBe('ssh');
  expect(host.querySelector<HTMLInputElement>('[aria-label="研究数据目录"]')!.value).toBe('/private/original');
  expect(host.querySelector<HTMLInputElement>('[aria-label="研究数据目录"]')!.disabled).toBe(true);
  expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled();
  expect(personalAgentApi.submit).not.toHaveBeenCalled();
});

it('does not start an SSH installation when no owned server is available', async () => {
  vi.mocked(applicationEnvironmentApi.capabilities).mockResolvedValue({ locations: ['ssh'], applications: ['openresearch'] });
  vi.spyOn(applicationEnvironmentApi, 'servers').mockResolvedValue([]);
  await mount();
  await act(async () => {
    const selector = host.querySelector<HTMLSelectElement>('[aria-label="运行位置"]')!;
    selector.value = 'ssh'; selector.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await goal('Synthetic retained draft');
  expect(button('开始研究').disabled).toBe(true);
  expect(host.textContent).toContain('暂无已启用的本人服务器');
  expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled();
});

it('an authoritative SSH directory rejection keeps the draft and lets the owner correct the selection', async () => {
  vi.mocked(applicationEnvironmentApi.capabilities).mockResolvedValue({ locations: ['ssh'], applications: ['openresearch'] });
  vi.spyOn(applicationEnvironmentApi, 'servers').mockResolvedValue([{ reference: 'owned-linux', name: 'My Linux', defaultDirectory: '/private/alice/research' }]);
  vi.mocked(applicationEnvironmentApi.prepare).mockRejectedValue(new ApiError('ENVIRONMENT_SSH_SELECTION_UNAVAILABLE', 409));
  await mount(); await goal('Synthetic retained draft'); await act(async () => button('开始研究').click());
  expect(host.textContent).toContain('服务器或目录未通过检查');
  expect(host.querySelector('.research-status')!.textContent).toContain('请修正服务器或目录');
  expect(host.querySelector('.research-status')!.textContent).not.toContain('可以开始研究');
  expect(host.querySelector<HTMLInputElement>('[aria-label="研究数据目录"]')!.getAttribute('aria-invalid')).toBe('true');
  expect(host.querySelector('[role="alert"]')!.id).toBe('research-environment-error');
  expect(host.querySelector<HTMLInputElement>('[aria-label="研究数据目录"]')!.disabled).toBe(false);
  expect(host.querySelector<HTMLTextAreaElement>('[aria-label="研究目标"], [aria-label="继续研究"]')!.value).toBe('Synthetic retained draft');
  expect(localStorage.getItem(`factory-environment-prepare:${owner.id}`)).toBeNull();
  expect(personalAgentApi.submit).not.toHaveBeenCalled();
});

it('reload finds owned original environment metadata then checks availability without preparing or sending work', async () => {
  vi.mocked(applicationEnvironmentApi.list).mockResolvedValue([env]);
  vi.mocked(applicationEnvironmentApi.inspect).mockResolvedValue({ ...env, state: 'unavailable' });
  await mount();
  expect(applicationEnvironmentApi.list).toHaveBeenCalledWith(owner.id, expect.any(AbortSignal));
  expect(applicationEnvironmentApi.inspect).toHaveBeenCalledWith(owner.id, env.id, expect.any(AbortSignal));
  expect(host.textContent).toContain('原环境当前不可用，原数据保留');
  expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.submit).not.toHaveBeenCalled();
});

it('a fresh browser discovers the original preparing request and blocks another goal or premature restore', async () => {
  const original = { ...env, state: 'preparing', lastOperation: { requestId: 'original-pending-prepare', action: 'prepare' as const, state: 'preparing' } };
  vi.mocked(applicationEnvironmentApi.list).mockResolvedValue([original]); vi.mocked(applicationEnvironmentApi.inspect).mockResolvedValue(original);
  await mount(); await goal('Synthetic retained pending goal');
  expect(localStorage.getItem(`factory-environment-prepare:${owner.id}`)).toBe('original-pending-prepare');
  expect(button('开始研究').disabled).toBe(true); expect(button('明确恢复平台环境').disabled).toBe(true);
  await act(async () => button('核对原环境准备').click());
  expect(applicationEnvironmentApi.recover).toHaveBeenLastCalledWith('original-pending-prepare');
  expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.submit).not.toHaveBeenCalled();
});

it('opening original history discovers its environment when the expired SSH binding is absent from usable servers', async () => {
  vi.mocked(applicationEnvironmentApi.capabilities).mockResolvedValue({ locations: ['ssh'], applications: ['openresearch'] });
  vi.spyOn(applicationEnvironmentApi, 'servers').mockResolvedValue([]);
  const original = { ...env, location: 'ssh' as const, serverRef: 'expired-owned-server', remoteDirectory: '/private/alice/research', state: 'unavailable' };
  const history = { id: 'session-fixture', nativeProjectId: env.projectId, nativeSessionId: 'native-session-fixture',
    namespace: 'native-openresearch', connectionRef: env.connectionRef, state: 'result_observed', activeRequestId: null,
    bindingStatus: 'unavailable', connectionPin: { ownerId: owner.id, capabilities: ['session:read', 'session:prompt'] }, observation: null } as unknown as PersonalSession;
  vi.mocked(personalAgentApi.sessions).mockResolvedValue([history]); vi.spyOn(personalAgentApi, 'session').mockResolvedValue(history);
  vi.mocked(applicationEnvironmentApi.list).mockResolvedValue([original, { ...original, id: 'unrelated-environment', projectId: 'unrelated-project' }]);
  vi.mocked(applicationEnvironmentApi.inspect).mockResolvedValue(original);
  await mount();
  const entry = host.querySelector<HTMLButtonElement>('.research-session-entry button')!;
  await act(async () => entry.click());
  expect(applicationEnvironmentApi.inspect).toHaveBeenCalledWith(owner.id, env.id, expect.any(AbortSignal));
  expect(host.textContent).toContain('服务器环境：原环境当前不可用，原数据保留');
  expect(host.textContent).toContain('核对恢复条件');
  expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.submit).not.toHaveBeenCalled();
});

it('explicit incompatible-package choice creates another environment without sending a retained goal', async () => {
  vi.mocked(applicationEnvironmentApi.list).mockResolvedValue([{ ...env, state: 'stopped' }]);
  vi.mocked(applicationEnvironmentApi.inspect).mockResolvedValue({ ...env, state: 'stopped' });
  vi.spyOn(applicationEnvironmentApi, 'continuation').mockResolvedValue({ environmentId: env.id, projectId: env.projectId,
    dataRetained: true, classification: 'needs-new-run', canRebind: false, requiresCredentialRebind: false,
    sessionRebindRequired: false, originalWorkReplay: false, researchSubmitted: false, nativeCheckpointContinuationVerified: false,
    reason: 'ENVIRONMENT_PACKAGE_CHANGED', nextAction: 'new-environment', message: '原项目与结果保留。' });
  const next = { ...env, id: 'env-'+'b'.repeat(32), projectId: 'new-project' };
  vi.mocked(applicationEnvironmentApi.prepare).mockImplementation(async (_, id) => {
    vi.mocked(applicationEnvironmentApi.list).mockResolvedValue([env,next]);
    vi.mocked(applicationEnvironmentApi.inspect).mockResolvedValue(next);
    return { ...request(id), environment: next };
  });
  vi.mocked(personalAgentApi.project).mockResolvedValue({ ...project, nativeProjectId: next.projectId, upstreamOrxProjectId: next.projectId });
  await mount(); await goal('Synthetic retained goal');
  await act(async () => button('核对恢复条件').click());
  expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled();
  await act(async () => button('创建新环境，保留旧结果').click());
  expect(applicationEnvironmentApi.prepare).toHaveBeenCalledWith(owner.id, expect.any(String), { location: 'platform', newEnvironment: true });
  expect(personalAgentApi.submit).not.toHaveBeenCalled(); expect(host.querySelector<HTMLTextAreaElement>('[aria-label="研究目标"], [aria-label="继续研究"]')!.value).toBe('Synthetic retained goal');
  await act(async () => root.unmount()); root=createRoot(host); await mount();
  expect(personalAgentApi.submit).not.toHaveBeenCalled();
  await act(async () => button('开始研究').click());
  expect(applicationEnvironmentApi.prepare).toHaveBeenLastCalledWith(owner.id,expect.any(String),{location:'platform',environmentId:next.id});
  expect(personalAgentApi.submit).toHaveBeenCalledTimes(1);
  expect(personalAgentApi.submit).toHaveBeenCalledWith(expect.objectContaining({nativeProjectId:next.projectId}),owner.id);
});

it('restores the stopped explicit generation with its own ID and does not send a goal', async () => {
  const generation = { ...env,id:'env-'+'b'.repeat(32),projectId:'distinct-generation-project',state:'stopped' };
  vi.mocked(applicationEnvironmentApi.list).mockResolvedValue([generation]); vi.mocked(applicationEnvironmentApi.inspect).mockResolvedValue(generation);
  vi.mocked(applicationEnvironmentApi.prepare).mockImplementation(async (_, id) => ({...request(id),environment:{...generation,state:'ready'}}));
  vi.mocked(personalAgentApi.project).mockResolvedValue({...project,nativeProjectId:generation.projectId});
  await mount(); await goal('SYNTHETIC retained goal');
  await act(async () => button('准备或恢复平台环境').click());
  expect(applicationEnvironmentApi.prepare).toHaveBeenCalledWith(owner.id,expect.any(String),{location:'platform',environmentId:generation.id});
  expect(personalAgentApi.submit).not.toHaveBeenCalled();
});

it('selects a new generation with a distinct connection after opening A, retaining A only in history across refresh',async()=>{
  const a={id:'research-A',nativeProjectId:env.projectId,nativeSessionId:'native-A',namespace:'native-openresearch',connectionRef:env.connectionRef,state:'result_observed',activeRequestId:null,bindingStatus:'unavailable',connectionPin:{ownerId:owner.id,capabilities:['session:read','session:prompt']},observation:null} as unknown as PersonalSession;
  const next={...env,id:'env-'+'b'.repeat(32),projectId:'new-generation-project',connectionRef:'binding-new-generation'};
  const sessionStorageKey=`factory-personal-session:${owner.id}:native-openresearch`;
  localStorage.setItem(sessionStorageKey,a.id);
  vi.mocked(personalAgentApi.sessions).mockResolvedValue([a]);vi.spyOn(personalAgentApi,'session').mockResolvedValue(a);
  vi.mocked(applicationEnvironmentApi.list).mockResolvedValue([env]);
  vi.mocked(applicationEnvironmentApi.inspect).mockImplementation(async(_,id)=>id===next.id?next:env);
  vi.spyOn(applicationEnvironmentApi,'continuation').mockResolvedValue({environmentId:env.id,projectId:env.projectId,dataRetained:true,classification:'needs-new-run',canRebind:false,requiresCredentialRebind:false,sessionRebindRequired:false,originalWorkReplay:false,researchSubmitted:false,nativeCheckpointContinuationVerified:false,reason:'ENVIRONMENT_PACKAGE_CHANGED',nextAction:'new-environment',message:'SYNTHETIC package change'});
  vi.mocked(applicationEnvironmentApi.prepare).mockImplementation(async(_,id)=>{vi.mocked(applicationEnvironmentApi.list).mockResolvedValue([env,next]);return {...request(id),environment:next};});
  vi.mocked(personalAgentApi.project).mockImplementation(async ref=>ref===next.connectionRef?{...project,nativeProjectId:next.projectId,upstreamOrxProjectId:next.projectId,connectionPin:{ref:next.connectionRef}}:project);
  await mount();expect(host.querySelector('.research-session-entry button')?.getAttribute('aria-pressed')).toBe('true');
  await goal('SYNTHETIC retained new research draft');await act(async()=>button('核对恢复条件').click());await act(async()=>button('创建新环境，保留旧结果').click());
  expect(localStorage.getItem(sessionStorageKey)).toBeNull();
  expect(JSON.parse(localStorage.getItem(`factory-environment-selection:${owner.id}`)!)).toEqual({id:next.id,projectId:next.projectId,connectionRef:next.connectionRef});
  expect(host.querySelector('.research-session-entry button')?.getAttribute('aria-pressed')).toBe('false');
  await act(async()=>root.unmount());root=createRoot(host);await mount();
  expect(host.querySelector('.research-session-entry button')?.getAttribute('aria-pressed')).toBe('false');
  expect(applicationEnvironmentApi.inspect).toHaveBeenLastCalledWith(owner.id,next.id,expect.any(AbortSignal));
  expect(applicationEnvironmentApi.prepare).toHaveBeenCalledTimes(1);expect(personalAgentApi.submit).not.toHaveBeenCalled();
  expect(host.querySelector<HTMLTextAreaElement>('[aria-label="研究目标"], [aria-label="继续研究"]')!.value).toBe('SYNTHETIC retained new research draft');
  // The original research remains readable and requires an explicit selection.
  await act(async()=>host.querySelector<HTMLButtonElement>('.research-session-entry button')!.click());
  expect(host.querySelector('.research-session-entry button')?.getAttribute('aria-pressed')).toBe('true');
  expect(personalAgentApi.submit).not.toHaveBeenCalled();
});

it.each(['missing','ambiguous','delayed'] as const)('revokes environment A writes when research B discovery is %s',async outcome => {
  const history = (id:string,projectId:string,connectionRef:string) => ({id,nativeProjectId:projectId,nativeSessionId:'native-'+id,namespace:'native-openresearch',connectionRef,state:'result_observed',activeRequestId:null,bindingStatus:'unavailable',connectionPin:{ownerId:owner.id,capabilities:['session:read','session:prompt']},observation:null}) as unknown as PersonalSession;
  const a=history('session-A',env.projectId,env.connectionRef); const b=history('session-B','project-B','binding-B');
  vi.mocked(personalAgentApi.sessions).mockResolvedValue([a,b]); vi.spyOn(personalAgentApi,'session').mockImplementation(async id=>id===a.id?a:b);
  vi.mocked(applicationEnvironmentApi.list).mockResolvedValue([env]);
  vi.spyOn(applicationEnvironmentApi,'stop'); vi.spyOn(applicationEnvironmentApi,'rebind');
  await mount();
  await act(async () => host.querySelectorAll<HTMLButtonElement>('.research-session-entry button')[0].click());
  expect(button('停止环境并保留数据')).toBeTruthy();
  const resolves: Array<(values: typeof env[]) => void> = [];
  const next = {...env,id:'env-'+'b'.repeat(32),projectId:'project-B',connectionRef:'binding-B'};
  if(outcome==='delayed') vi.mocked(applicationEnvironmentApi.list).mockImplementation(()=>new Promise(done=>{resolves.push(done);}));
  else vi.mocked(applicationEnvironmentApi.list).mockResolvedValue(outcome==='missing'?[]:[next,{...next,id:'env-'+'c'.repeat(32)}]);
  await act(async () => host.querySelectorAll<HTMLButtonElement>('.research-session-entry button')[1].click());
  expect(button('停止环境并保留数据')).toBeUndefined(); expect(button('核对恢复条件')).toBeUndefined();
  if(outcome==='delayed') {
    await act(async () => host.querySelectorAll<HTMLButtonElement>('.research-session-entry button')[0].click());
    // B's delayed response cannot establish a write target after returning A.
    await act(async()=>resolves[0]([next]));
    expect(button('停止环境并保留数据')).toBeUndefined();
    await act(async()=>resolves.at(-1)!([env]));
    expect(button('停止环境并保留数据')).toBeTruthy();
  }
  expect(applicationEnvironmentApi.stop).not.toHaveBeenCalled(); expect(applicationEnvironmentApi.rebind).not.toHaveBeenCalled();
  expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.submit).not.toHaveBeenCalled();
});

it('ignores late original environment inspect after switching research identity',async()=>{
  const history=(id:string,projectId:string,ref:string)=>({id,nativeProjectId:projectId,nativeSessionId:'native-'+id,namespace:'native-openresearch',connectionRef:ref,state:'result_observed',activeRequestId:null,bindingStatus:'unavailable',connectionPin:{ownerId:owner.id,capabilities:['session:read','session:prompt']},observation:null}) as unknown as PersonalSession;
  const a=history('A',env.projectId,env.connectionRef),b=history('B','project-B','binding-B');
  vi.mocked(personalAgentApi.sessions).mockResolvedValue([a,b]);vi.spyOn(personalAgentApi,'session').mockImplementation(async id=>id===a.id?a:b);
  vi.mocked(applicationEnvironmentApi.list).mockResolvedValue([env]);
  let finish!: (value:typeof env)=>void;
  vi.mocked(applicationEnvironmentApi.inspect).mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
  await mount();await act(async()=>host.querySelectorAll<HTMLButtonElement>('.research-session-entry button')[0].click());
  expect(button('停止环境并保留数据')).toBeUndefined();
  vi.mocked(applicationEnvironmentApi.list).mockResolvedValue([]);
  await act(async()=>host.querySelectorAll<HTMLButtonElement>('.research-session-entry button')[1].click());
  await act(async()=>finish(env));
  expect(button('停止环境并保留数据')).toBeUndefined();expect(button('核对恢复条件')).toBeUndefined();
  expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled();expect(personalAgentApi.submit).not.toHaveBeenCalled();
});

it('retains original A recovery custody without restoring default or A after selecting research B',async()=>{
  localStorage.setItem(`factory-environment-prepare:${owner.id}`,'original-A-prepare');
  const unknown={...env,state:'unknown'};
  vi.mocked(applicationEnvironmentApi.recover).mockImplementation(async id=>({...request(id),state:'unknown',environment:unknown}));
  const b={id:'session-B',nativeProjectId:'project-B',nativeSessionId:'native-B',namespace:'native-openresearch',connectionRef:'binding-B',state:'result_observed',activeRequestId:null,bindingStatus:'unavailable',connectionPin:{ownerId:owner.id,capabilities:['session:read','session:prompt']},observation:null} as unknown as PersonalSession;
  vi.mocked(personalAgentApi.sessions).mockResolvedValue([b]);vi.spyOn(personalAgentApi,'session').mockResolvedValue(b);
  await mount();await act(async()=>host.querySelector<HTMLButtonElement>('.research-session-entry button')!.click());
  expect(button('明确恢复平台环境').disabled).toBe(true);
  await act(async()=>button('明确恢复平台环境').click());
  expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled();expect(personalAgentApi.submit).not.toHaveBeenCalled();
  expect(localStorage.getItem(`factory-environment-prepare:${owner.id}`)).toBe('original-A-prepare');
  expect(button('停止环境并保留数据')).toBeUndefined();expect(button('核对恢复条件')).toBeUndefined();
});

it('lost stop acknowledgement survives reload and only reads the original stop request', async () => {
  vi.mocked(applicationEnvironmentApi.list).mockResolvedValue([env]);
  vi.spyOn(applicationEnvironmentApi, 'stop').mockRejectedValue(new Error('lost stop acknowledgement'));
  await mount(); await act(async () => button('停止环境并保留数据').click());
  const original = localStorage.getItem(`factory-environment-prepare:${owner.id}`)!;
  expect(original).toBeTruthy(); expect(localStorage.getItem(`factory-environment-prepare:${owner.id}:action`)).toBe('stop');
  vi.mocked(applicationEnvironmentApi.recover).mockImplementation(async id => ({ ...request(id), action: 'stop', state: 'stopped', environment: { ...env, state: 'stopped' } }));
  await act(async () => root.unmount()); root = createRoot(host); await mount();
  await act(async () => button('核对原环境停止').click());
  expect(applicationEnvironmentApi.stop).toHaveBeenCalledTimes(1);
  expect(applicationEnvironmentApi.recover).toHaveBeenLastCalledWith(original);
  expect(localStorage.getItem(`factory-environment-prepare:${owner.id}`)).toBeNull();
  expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.submit).not.toHaveBeenCalled();
});

it('positive pre-install credential rejection preserves the goal and points to recovery instead of an absent request', async () => {
  vi.mocked(applicationEnvironmentApi.list).mockResolvedValue([env]);
  vi.mocked(applicationEnvironmentApi.prepare).mockRejectedValue(new ApiError('ENVIRONMENT_MODEL_CHANGED: explicit migration required', 409, 'REQUEST_REJECTED'));
  await mount(); await goal('Synthetic retained credential-change goal'); await act(async () => button('开始研究').click());
  expect(host.querySelector('.research-status')!.textContent).toContain('请核对原环境恢复条件');
  expect(localStorage.getItem(`factory-environment-prepare:${owner.id}`)).toBeNull();
  expect(host.querySelector<HTMLTextAreaElement>('[aria-label="研究目标"], [aria-label="继续研究"]')!.value).toBe('Synthetic retained credential-change goal');
  expect(personalAgentApi.submit).not.toHaveBeenCalled();
});

it('shows SSH infrastructure and manual registration prerequisites before the start button', async () => {
  vi.mocked(applicationEnvironmentApi.capabilities).mockResolvedValue({ locations: ['ssh'], applications: ['openresearch'] });
  vi.spyOn(applicationEnvironmentApi, 'servers').mockResolvedValue([{ reference: 'owned-linux', name: 'My Linux', defaultDirectory: '/private/alice/research' }]);
  await mount();
  const requirements = host.querySelector('#research-ssh-prerequisites')!;
  for (const text of ['Python 3.12+', 'Docker', '非 root', 'SSH 账户', '先注册服务器', '此部署尚未启用自助注册', '不安装系统依赖']) expect(requirements.textContent).toContain(text);
  expect(requirements.compareDocumentPosition(button('开始研究')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled();
});

it('exposes existing research outside collapsed settings and opens it without creating or prompting', async () => {
  const existing = { id: 'original-study', namespace: 'native-openresearch', connectionRef: 'original-binding',
    nativeSessionId: 'original-session', nativeProjectId: 'original-project', state: 'result_observed',
    observation: { messages: [{ id: 'goal', role: 'user', completed: false, events: [{ type: 'text', text: 'Synthetic original research' }] },
      { id: 'reply', role: 'assistant', completed: true, events: [{ type: 'text', text: 'Synthetic retained result' }] }] } } as PersonalSession;
  vi.mocked(personalAgentApi.sessions).mockResolvedValue([existing]);
  await mount();
  const entry = host.querySelector('section[aria-label="已有研究"]')!;
  expect(entry.closest('details')).toBeNull();
  expect(entry.textContent).toContain('Synthetic original research');
  await act(async () => button('Synthetic original research').click());
  expect(host.querySelector('[aria-label="研究结果"]')!.textContent).toContain('Synthetic retained result');
  expect(localStorage.getItem(`factory-personal-session:${owner.id}:native-openresearch`)).toBe(existing.id);
  expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.submit).not.toHaveBeenCalled();
});


it('distinguishes a failed identity/capability read from loading and retries without dispatching', async () => {
  vi.mocked(personalAgentApi.capabilities).mockRejectedValue(new Error('synthetic unavailable'));
  sessionStorage.setItem(`factory-research-draft:${owner.id}`, JSON.stringify({goal:'Synthetic preserved draft',materials:''}));
  await mount();
  expect(host.querySelector('[aria-label="研究进度"]')!.textContent).toContain('暂时无法读取研究连接');
  expect(button('开始研究').disabled).toBe(true);
  expect(host.querySelector<HTMLTextAreaElement>('[aria-label="研究目标"], [aria-label="继续研究"]')!.value).toBe('Synthetic preserved draft');
  vi.mocked(personalAgentApi.capabilities).mockResolvedValue({executionContract:PERSONAL_CONTRACT,nativeQueue:true,ownerSubmit:'/api/factory/personal-agent/commands/submit',modelConfiguration:'remote-configured-model',factoryBYOKForwarded:false});
  await act(async () => button('刷新').click());
  expect(host.querySelector('[aria-label="研究进度"]')!.textContent).toContain('可以开始研究');
  expect(button('开始研究').disabled).toBe(false);
  expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.submit).not.toHaveBeenCalled();
});

it('keeps old replies distinct from a pending turn and exposes original tool evidence without new requests', async () => {
  const existing = {id:'evidence-study',namespace:'native-openresearch',connectionRef:'original-binding',nativeSessionId:'native-original',nativeProjectId:'project-original',state:'ack_unknown',activeRequestId:'unknown-original',factoryIdentity:{taskId:'task-original'},
    observation:{exactTurnVerified:false,messages:[{id:'g',role:'user',events:[{type:'text',text:'Synthetic original goal'}]},{id:'r',role:'assistant',completed:true,events:[{type:'text',text:'Synthetic older result'},{type:'tool',tool:'read_local_fixture',status:'completed',output:'Synthetic recorded tool output'}]}]}} as unknown as PersonalSession;
  vi.mocked(personalAgentApi.sessions).mockResolvedValue([existing]);
  await mount(); await act(async () => button('Synthetic original goal').click());
  expect(host.querySelector('[aria-label="目标与下一步"]')!.textContent).toContain('Synthetic original goal');
  expect(host.querySelector('[aria-label="研究进度"]')!.textContent).toContain('研究请求待核对');
  expect(host.querySelector('[aria-label="研究进度"]')!.textContent).toContain('已有回复可能来自上一轮');
  expect(host.querySelector('[aria-label="研究结果"]')!.textContent).toContain('Synthetic older result');
  expect(host.querySelector('[aria-label="证据与来源"]')!.textContent).toContain('Synthetic recorded tool output');
  expect(host.querySelector('[aria-label="证据与来源"]')!.textContent).toContain('精确轮次未验证');
  expect(button('继续研究').disabled).toBe(true);
  expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.submit).not.toHaveBeenCalled();
});
