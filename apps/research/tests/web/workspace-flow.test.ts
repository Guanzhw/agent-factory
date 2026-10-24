// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Workspace } from '../../../../web/composition.js';
import { api } from '../../../../web/api.js';
import { researchApi } from '../../web/api.js';
import { personalAgentApi, type PersonalSession } from '../../web/personalAgentApi.js';
import { personalRemoteApi } from '../../../../web/personalRemoteApi.js';
import { openresearchApi } from '../../web/openresearchApi.js';
import { applicationEnvironmentApi, type ApplicationEnvironment } from '../../web/applicationEnvironmentApi.js';
import { personalSSHApi, type PersonalSSHServer } from '../../../../web/personalSSHApi.js';
import { ownerModelApi, type OwnerModel } from '../../../../web/ownerModelApi.js';
import { personalToolConnectionApi } from '../../../../web/personalToolConnectionApi.js';
import type { User } from '../../../../web/models.js';
vi.mock('../../web/openresearchApi.js', () => ({ openresearchApi: { capabilities: vi.fn(), projects: vi.fn(), project: vi.fn(), sessions: vi.fn(), managedProfiles: vi.fn() } }));
vi.mock('../../web/personalAgentApi.js', async importOriginal => { const original = await importOriginal<typeof import('../../web/personalAgentApi.js')>(); return { ...original, personalAgentApi: { ...original.personalAgentApi, capabilities: vi.fn(), sessions: vi.fn(), prepare: vi.fn(), submit: vi.fn() } }; });
vi.mock('../../web/applicationEnvironmentApi.js', async importOriginal => { const original = await importOriginal<typeof import('../../web/applicationEnvironmentApi.js')>(); return { ...original, applicationEnvironmentApi: { ...original.applicationEnvironmentApi, prepare: vi.fn(), capabilities: vi.fn(), servers: vi.fn() } }; });
vi.mock('../../../../web/personalRemoteApi.js', async importOriginal => { const original = await importOriginal<typeof import('../../../../web/personalRemoteApi.js')>(); return { ...original, personalRemoteApi: { ...original.personalRemoteApi, list: vi.fn(), credentials: vi.fn(), providers: vi.fn(), credentialAvailability: vi.fn() } }; });
vi.mock('../../../../web/personalSSHApi.js', async importOriginal => { const original = await importOriginal<typeof import('../../../../web/personalSSHApi.js')>(); return { ...original, personalSSHApi: { ...original.personalSSHApi, capabilities: vi.fn(), list: vi.fn() } }; });
vi.mock('../../../../web/ownerModelApi.js', async importOriginal => { const original = await importOriginal<typeof import('../../../../web/ownerModelApi.js')>(); return { ...original, ownerModelApi: { ...original.ownerModelApi, list: vi.fn() } }; });
vi.mock('../../../../web/personalToolConnectionApi.js', async importOriginal => { const original = await importOriginal<typeof import('../../../../web/personalToolConnectionApi.js')>(); return { ...original, personalToolConnectionApi: { ...original.personalToolConnectionApi, descriptors: vi.fn(), list: vi.fn() } }; });
vi.mock('../../../../web/ControlRecovery.js', () => ({ ControlRecovery: () => null, commandNotice: () => '' }));
vi.mock('../../../../web/CompositionInbox.js', () => ({ CompositionInbox: () => createElement('p', null, '历史提案内容') }));
vi.mock('../../../../web/ApplicationGovernance.js', () => ({ ApplicationGovernance: () => createElement('p', null, '应用管理内容') }));
vi.mock('../../../../web/api.js', async importOriginal => {
  const original = await importOriginal<typeof import('../../../../web/api.js')>();
  return { ...original, api: { ...original.api,
    status: vi.fn(), materials: vi.fn(), jobs: vi.fn(), executionTargets: vi.fn(), session: vi.fn(), applications: vi.fn(), userConnections: vi.fn(), detail: vi.fn(),
  } };
});
vi.mock('../../web/api.js', async importOriginal => {
  const original = await importOriginal<typeof import('../../web/api.js')>();
  return { ...original, researchApi: { ...original.researchApi,
    autoresearch: { presets: vi.fn(), get: vi.fn(), recover: vi.fn(), start: vi.fn(), cancel: vi.fn() },
  } };
});
const alice: User = { id: 'alice', name: 'Alice', role: 'user' };
let host: HTMLDivElement; let root: Root;
const text = () => host.textContent ?? '';
async function render(user = alice) { await act(async () => { root.render(createElement(Workspace, { user, logout: () => {}, sessionBusy: false, sessionError: '' })); }); }
async function click(label: string) {
  const button = Array.from(host.querySelectorAll('button')).find(button => button.textContent === label);
  expect(button, `button ${label}`).toBeTruthy();
  await act(async () => { button!.click(); });
}
beforeEach(() => {
  vi.clearAllMocks(); window.history.replaceState(null, '', '/'); window.sessionStorage.clear(); window.localStorage.clear();
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network is forbidden in the workspace fixture')));
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  vi.mocked(api.status).mockResolvedValue({ mode: 'demo', activeWorkers: 0, queuedJobs: 0, maxWorkers: 2 } as Awaited<ReturnType<typeof api.status>>);
  vi.mocked(api.materials).mockResolvedValue([]); vi.mocked(api.jobs).mockResolvedValue([]); vi.mocked(api.executionTargets).mockResolvedValue([]);
  vi.mocked(api.session).mockResolvedValue(alice); vi.mocked(api.applications).mockResolvedValue([]); vi.mocked(api.userConnections).mockResolvedValue([]);
  vi.mocked(personalToolConnectionApi.descriptors).mockResolvedValue([]); vi.mocked(personalToolConnectionApi.list).mockResolvedValue([]);
  vi.mocked(personalAgentApi.sessions).mockResolvedValue([]); vi.mocked(personalAgentApi.capabilities).mockResolvedValue({ executionContract: 'personal-external-v1', nativeQueue: true }); vi.mocked(personalRemoteApi.list).mockResolvedValue([]);
  vi.mocked(personalRemoteApi.providers).mockResolvedValue([]); vi.mocked(personalRemoteApi.credentialAvailability).mockResolvedValue({ enabled: false, providerIds: [] });
  vi.mocked(openresearchApi.capabilities).mockResolvedValue({ contractVersion: 1, nativeProjectAttachment: true, upstreamProjectCreation: false, liveEndToEndVerified: false, workloads: [] }); vi.mocked(openresearchApi.projects).mockResolvedValue([]);
  vi.mocked(researchApi.autoresearch.presets).mockResolvedValue([]); vi.mocked(api.detail).mockRejectedValue(new Error('任务不存在或无权访问'));
  vi.mocked(personalSSHApi.capabilities).mockResolvedValue({enabled:false});vi.mocked(personalSSHApi.list).mockResolvedValue([]);
  vi.mocked(personalRemoteApi.credentials).mockResolvedValue([]);vi.mocked(applicationEnvironmentApi.capabilities).mockResolvedValue({locations:[],applications:[]});vi.mocked(applicationEnvironmentApi.servers).mockResolvedValue([]);vi.mocked(ownerModelApi.list).mockResolvedValue([]);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function chooseServerB(options: { environmentUnknown?: boolean; savedRequest?: boolean; researchUnknown?: boolean; bindingUnknown?: boolean; requestDuringRead?: boolean; recoveryDuringRead?: 'environment' | 'command' | 'binding'; inspectionFails?: boolean; historyOnly?: boolean } = {}) {
    const server = (digit: string, name: string): PersonalSSHServer => ({ reference: 'remote-' + digit.repeat(32), name, address: '127.0.0.1', port: 2222, username: 'fixture', hostKey: 'ssh-ed25519 ' + 'A'.repeat(68), hostFingerprint: 'SHA256:synthetic-host-fingerprint', allowedRoot: '/tmp/af-owned-fixture', defaultDirectory: '/tmp/af-owned-fixture/' + name, status: 'verified', enabled: true, diagnostic: null, lastCheckRequestId: null, credentialRef: 'fixture-key', credentialRevision: 'one' });
    vi.mocked(personalAgentApi.capabilities).mockResolvedValue({ executionContract: 'personal-external-v1', nativeQueue: true, ownerSubmit: '/api/factory/personal-agent/commands/submit', modelConfiguration: 'remote-configured-model', factoryBYOKForwarded: false });
    vi.mocked(ownerModelApi.list).mockResolvedValue([{ isDefault: true, available: true } as OwnerModel]);
    sessionStorage.setItem('factory-research-draft:alice', JSON.stringify({ goal: 'Synthetic retained goal', materials: '' }));
    const a = server('a', 'server-A'); const b = server('b', 'server-B');
    const original: ApplicationEnvironment = { id: 'env-' + 'a'.repeat(32), applicationId: 'openresearch', location: 'ssh', serverRef: a.reference, remoteDirectory: a.defaultDirectory, state: 'ready', packageVersion: 'fixture-package', projectId: 'project-A', connectionRef: 'binding-A', modelReference: 'fixture-model', modelRevision: 'one', dataRetained: true, researchSubmitted: false };
    if (options.environmentUnknown || options.savedRequest) { original.state = 'unknown'; original.lastOperation = { requestId: 'original-A-unknown', action: 'prepare', state: 'unknown' }; }
    const history = { id: 'study-A', nativeProjectId: original.projectId, nativeSessionId: 'native-A', namespace: 'native-openresearch', connectionRef: original.connectionRef, state: 'result_observed', activeRequestId: null, bindingStatus: 'unavailable', connectionPin: { ownerId: alice.id, capabilities: ['session:read', 'session:prompt'] }, observation: null } as unknown as PersonalSession;
    if (options.researchUnknown) { history.state = 'ack_unknown'; history.activeRequestId = 'original-A-command'; }
    const selection = { id: original.id, projectId: original.projectId, connectionRef: original.connectionRef };
    localStorage.setItem('factory-environment-selection:alice', JSON.stringify(selection));
    if (options.historyOnly) localStorage.removeItem('factory-environment-selection:alice');
    localStorage.setItem('factory-personal-session:alice:native-openresearch', history.id);
    if (options.savedRequest) localStorage.setItem('factory-environment-prepare:alice', 'original-A-unknown');
    const bindingKey = 'factory-environment-binding:alice:' + original.id;
    const binding = JSON.stringify({ requestId: 'binding-A-unknown', previewHash: 'b'.repeat(64), projectId: original.projectId, environmentId: original.id });
    if (options.bindingUnknown) localStorage.setItem(bindingKey, binding);
    vi.mocked(personalSSHApi.capabilities).mockResolvedValue({ enabled: true }); vi.mocked(personalSSHApi.list).mockResolvedValue([a, b]);
    vi.mocked(applicationEnvironmentApi.capabilities).mockResolvedValue({ locations: ['ssh'], applications: ['openresearch'] });
    vi.mocked(applicationEnvironmentApi.servers).mockResolvedValue([a, b]);
    vi.spyOn(applicationEnvironmentApi, 'list').mockResolvedValue([original]);
    let recoveryPersisted = false;
    let inspectionFailed = false;
    vi.spyOn(applicationEnvironmentApi, 'inspect').mockImplementation(async () => {
      if (!recoveryPersisted) {
        recoveryPersisted = true;
      if (options.requestDuringRead || options.recoveryDuringRead === 'environment') localStorage.setItem('factory-environment-prepare:alice', 'original-A-unknown');
      if (options.recoveryDuringRead === 'command') localStorage.setItem('factory-personal-command:alice:native-openresearch', JSON.stringify({ requestId: 'original-A-command', submitAttempt: true }));
      if (options.recoveryDuringRead === 'binding') localStorage.setItem(bindingKey, binding);
      }
      if (options.inspectionFails && !inspectionFailed) { inspectionFailed = true; throw new Error('Synthetic inspection unavailable'); }
      return original;
    });
    vi.spyOn(applicationEnvironmentApi, 'recover').mockResolvedValue({ requestId: 'original-A-unknown', action: 'prepare', state: 'unknown', diagnostic: null, environment: original });
    vi.mocked(personalAgentApi.sessions).mockResolvedValue([history]);
    vi.spyOn(personalAgentApi, 'session').mockResolvedValue(history);
    vi.spyOn(personalAgentApi, 'snapshot').mockResolvedValue(history);
    window.history.replaceState(null, '', '/?tab=connections'); await render();
    const card = [...host.querySelectorAll('article')].find(item => item.querySelector('h3')?.textContent === b.name)!;
    await act(async () => [...card.querySelectorAll('button')].find(item => item.textContent === '去 OpenResearch 准备')!.click());
    return { b, original, history, selection, bindingKey, binding };
}
describe('workspace mounted application boundaries', () => {
  it('explicit SSH server B replaces only saved A viewing selections without preparing or submitting', async () => {
    const { b } = await chooseServerB();
    expect(host.querySelector<HTMLSelectElement>('[aria-label="我的服务器"]')?.value).toBe(b.reference);
    expect(host.querySelector<HTMLInputElement>('[aria-label="研究数据目录"]')?.value).toBe(b.defaultDirectory);
    expect(localStorage.getItem('factory-environment-selection:alice')).toBeNull();
    expect(localStorage.getItem('factory-personal-session:alice:native-openresearch')).toBeNull();
    expect(host.querySelector('.research-session-entry')?.textContent).toContain('查看已有研究');
    expect([...host.querySelectorAll('button')].find(button => button.textContent === '开始研究')?.disabled).toBe(false);
    expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.submit).not.toHaveBeenCalled();
  });
  it.each([
    ['saved environment UNKNOWN', { savedRequest: true }],
    ['discovered environment UNKNOWN', { environmentUnknown: true }],
    ['research UNKNOWN without a local command key', { researchUnknown: true }],
    ['unconfirmed credential binding', { bindingUnknown: true }],
    ['request persisted during the original inspection', { requestDuringRead: true }],
    ['environment UNKNOWN with only a saved study pointer', { environmentUnknown: true, historyOnly: true }],
  ] as const)('explicit server navigation retains A custody for %s', async (_, options) => {
    const { selection, history, bindingKey, binding, b } = await chooseServerB(options);
    if ('historyOnly' in options) expect(localStorage.getItem('factory-environment-selection:alice')).toBeNull();
    else expect(JSON.parse(localStorage.getItem('factory-environment-selection:alice')!)).toEqual(selection);
    expect(localStorage.getItem('factory-personal-session:alice:native-openresearch')).toBe(history.id);
    expect(JSON.parse(sessionStorage.getItem('factory-research-server:alice')!).reference).toBe(b.reference);
    if ('savedRequest' in options || 'environmentUnknown' in options || 'requestDuringRead' in options) expect(localStorage.getItem('factory-environment-prepare:alice')).toBe('original-A-unknown');
    if ('bindingUnknown' in options) expect(localStorage.getItem(bindingKey)).toBe(binding);
    if ('researchUnknown' in options) expect(host.textContent).toContain('需要核对原请求');
    expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.submit).not.toHaveBeenCalled();
  });
  it.each([['environment', false], ['command', false], ['binding', false], ['environment', true], ['command', true], ['binding', true]] as const)('reconciles %s recovery added during inspection (read failure %s) before allowing owner writes', async (kind, inspectionFails) => {
    const commandRecover = vi.spyOn(personalAgentApi, 'recover').mockRejectedValue(new Error('Synthetic unknown receipt'));
    const bindingRecover = vi.spyOn(applicationEnvironmentApi, 'bindingRequest').mockRejectedValue(new Error('Synthetic unknown receipt'));
    const { bindingKey, binding } = await chooseServerB({ recoveryDuringRead: kind, inspectionFails });
    const key = kind === 'environment' ? 'factory-environment-prepare:alice' : kind === 'command' ? 'factory-personal-command:alice:native-openresearch' : bindingKey;
    const original = localStorage.getItem(key);
    const label = kind === 'environment' ? '核对原环境准备' : kind === 'command' ? '核对研究请求' : '核对原绑定请求';
    expect([...host.querySelectorAll('button')].some(button => button.textContent === label)).toBe(true);
    if (kind === 'command') expect(text()).toContain('original-A-command');
    const writes = [...host.querySelectorAll<HTMLButtonElement>('button')].filter(button => /^(准备或恢复|明确恢复|开始研究$|继续研究$)/.test(button.textContent ?? ''));
    expect(writes.length).toBeGreaterThan(0);
    for (const button of writes) { expect(button.disabled).toBe(true); await act(async () => button.click()); }
    await click(label);
    expect(localStorage.getItem(key)).toBe(original);
    if (kind === 'environment') expect(applicationEnvironmentApi.recover).toHaveBeenLastCalledWith('original-A-unknown');
    if (kind === 'command') expect(commandRecover).toHaveBeenCalledWith('original-A-command');
    if (kind === 'binding') { expect(bindingRecover).toHaveBeenCalledWith('alice', 'binding-A-unknown'); expect(original).toBe(binding); }
    expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.submit).not.toHaveBeenCalled();
  });
  it.each(['environment', 'binding'] as const)('unfreezes ordinary recovery after the original %s receipt settles', async kind => {
    const { original } = await chooseServerB({ recoveryDuringRead: kind });
    if (kind === 'environment') {
      vi.mocked(applicationEnvironmentApi.recover).mockResolvedValue({ requestId: 'original-A-unknown', action: 'prepare', state: 'ready', diagnostic: null, environment: original });
      await click('核对原环境准备');
      expect([...host.querySelectorAll('button')].find(button => button.textContent === '明确恢复服务器环境')?.disabled).toBe(false);
    } else {
      vi.spyOn(applicationEnvironmentApi, 'bindingRequest').mockResolvedValue({ requestId: 'binding-A-unknown', state: 'committed', environment: original, runtimePrepared: false, researchSubmitted: false });
      await click('核对原绑定请求');
      expect([...host.querySelectorAll('button')].find(button => button.textContent === '准备或恢复服务器环境')?.disabled).toBe(false);
    }
    expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.submit).not.toHaveBeenCalled();
  });
  it('groups application, resource and task entry points while leaving advanced tools collapsed', async () => {
    await render();
    const primary = [...host.querySelectorAll('nav > button')].map(button => button.textContent);
    expect(primary).toEqual(['应用', '资源', '任务', '高级与管理']);
    expect(host.querySelector('#secondary-navigation')?.classList.contains('expanded')).toBe(false);
    await click('资源');
    expect(window.location.search).toContain('tab=resources');
    expect(host.querySelector('h1')?.textContent).toBe('我的资源');
    expect(text()).toContain('设置我的模型/API'); expect(text()).toContain('管理服务器与连接');
    expect(text()).toContain('都需要在应用中明确发起');
    expect(researchApi.autoresearch.start).not.toHaveBeenCalled();
    await click('任务'); expect(text()).toContain('选择已有任务查看进度');
    await click('进入 OpenResearch'); expect(window.location.search).toContain('tab=openresearch');
    expect(personalAgentApi.sessions).toHaveBeenCalled();
    expect(researchApi.autoresearch.start).not.toHaveBeenCalled();
  });
  it('restores resources on refresh and uses Back without creating work', async () => {
    window.history.replaceState(null, '', '/?tab=resources'); await render();
    expect(host.querySelector('h1')?.textContent).toBe('我的资源');
    await click('应用');
    await act(async () => { window.history.back(); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(host.querySelector('h1')?.textContent).toBe('我的资源');
    await act(async () => root.unmount()); root = createRoot(host); await render();
    expect(host.querySelector('h1')?.textContent).toBe('我的资源');
    expect(researchApi.autoresearch.start).not.toHaveBeenCalled();
  });
  it('retains the models return source after refresh and Back/Forward', async () => {
    window.history.replaceState(null, '', '/?tab=resources'); await render();
    await click('设置我的模型/API');
    expect(window.location.search).toContain('modelReturn=resources');
    await act(async () => root.unmount()); root = createRoot(host); await render();
    expect(host.querySelector('h1')?.textContent).toBe('我的模型/API');
    await click('返回工作区'); expect(host.querySelector('h1')?.textContent).toBe('我的资源');
    await act(async () => { window.history.back(); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(host.querySelector('h1')?.textContent).toBe('我的模型/API');
    await act(async () => { window.history.forward(); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(host.querySelector('h1')?.textContent).toBe('我的资源');
    await act(async () => { window.history.back(); await new Promise(resolve => setTimeout(resolve, 20)); });
    await click('返回工作区'); expect(host.querySelector('h1')?.textContent).toBe('我的资源');
    expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled();
    expect(personalAgentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.submit).not.toHaveBeenCalled();
  });
  it('returns from resources and refreshed models to the same managed project', async () => {
    const project = { id: 'orp-one', name: '合成受管项目', description: '', kind: 'native-openresearch' as const, upstreamProjectId: 'native-one', connectionRefs: {} };
    vi.mocked(openresearchApi.project).mockResolvedValue(project);
    vi.mocked(openresearchApi.projects).mockResolvedValue([project]); vi.mocked(openresearchApi.sessions).mockResolvedValue([]); vi.mocked(openresearchApi.managedProfiles).mockResolvedValue([]);
    window.history.replaceState(null, '', '/?tab=openresearch&mode=managed&project=orp-one'); await render();
    expect(host.querySelector('h1')?.textContent).toBe(project.name);
    await click('管理我的资源'); await click('设置我的模型/API');
    await act(async () => root.unmount()); root = createRoot(host); await render();
    await click('返回工作区'); await click('返回 OpenResearch');
    expect(host.querySelector('h1')?.textContent).toBe(project.name);
    expect(new URL(window.location.href).searchParams.get('mode')).toBe('managed');
    expect(new URL(window.location.href).searchParams.get('project')).toBe(project.id);
    await act(async () => { window.history.back(); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(host.querySelector('h1')?.textContent).toBe('我的资源');
    await act(async () => { window.history.forward(); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(host.querySelector('h1')?.textContent).toBe(project.name);
    expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled();
    expect(personalAgentApi.prepare).not.toHaveBeenCalled(); expect(personalAgentApi.submit).not.toHaveBeenCalled();
    expect(researchApi.autoresearch.start).not.toHaveBeenCalled();
  });
  it('keeps general connection return managed but enters personal research for an explicitly chosen SSH server',async()=>{
    const project={id:'orp-one',name:'合成受管项目',description:'',kind:'native-openresearch' as const,upstreamProjectId:'native-one',connectionRefs:{}};
    vi.mocked(openresearchApi.project).mockResolvedValue(project);vi.mocked(openresearchApi.projects).mockResolvedValue([project]);vi.mocked(openresearchApi.sessions).mockResolvedValue([]);vi.mocked(openresearchApi.managedProfiles).mockResolvedValue([]);
    const server:PersonalSSHServer={reference:'remote-'+'a'.repeat(32),name:'合成已启用服务器',address:'127.0.0.1',port:2222,username:'fixture',hostKey:'ssh-ed25519 '+'A'.repeat(68),hostFingerprint:'SHA256:synthetic-host-fingerprint',allowedRoot:'/tmp/af-owned-fixture',defaultDirectory:'/tmp/af-owned-fixture/research',status:'verified',enabled:true,diagnostic:null,lastCheckRequestId:null,credentialRef:'fixture-key',credentialRevision:'one'};
    vi.mocked(personalSSHApi.capabilities).mockResolvedValue({enabled:true});vi.mocked(personalSSHApi.list).mockResolvedValue([server]);
    vi.mocked(applicationEnvironmentApi.capabilities).mockResolvedValue({locations:['ssh'],applications:['openresearch']});
    vi.mocked(applicationEnvironmentApi.servers).mockResolvedValue([{reference:server.reference,name:server.name,defaultDirectory:server.defaultDirectory}]);
    window.history.replaceState(null,'','/?tab=openresearch&mode=managed&project=orp-one');await render();
    await click('管理我的资源');await click('管理服务器与连接');await click('返回 OpenResearch');
    expect(host.querySelector('h1')?.textContent).toBe(project.name);expect(new URL(window.location.href).searchParams.get('mode')).toBe('managed');
    await click('管理我的资源');await click('管理服务器与连接');await click('去 OpenResearch 准备');
    expect(new URL(window.location.href).searchParams.get('mode')).toBe('personal');expect(new URL(window.location.href).searchParams.get('project')).toBeNull();
    expect(host.querySelector('h1')?.textContent).toBe('OpenResearch');
    expect(host.querySelector<HTMLSelectElement>('[aria-label="运行位置"]')?.value).toBe('ssh');
    expect(host.querySelector<HTMLSelectElement>('[aria-label="我的服务器"]')?.value).toBe(server.reference);
    expect(host.querySelector<HTMLInputElement>('[aria-label="研究数据目录"]')?.value).toBe(server.defaultDirectory);
    expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled();expect(personalAgentApi.prepare).not.toHaveBeenCalled();expect(personalAgentApi.submit).not.toHaveBeenCalled();expect(researchApi.autoresearch.start).not.toHaveBeenCalled();
  });
  it('opens the catalog and places composition only in the developer entry', async () => {
    await render();
    expect(host.querySelector('h1')?.textContent).toBe('应用目录');
    expect(text()).toContain('选择应用，开始工作。');
    expect(Array.from(host.querySelectorAll('main h2'), heading => heading.textContent)).toEqual(['OpenResearch']);
    expect(host.querySelector('#application-selector')).toBeNull();
    expect(text()).toContain('进入 OpenResearch');
    expect(text()).not.toContain('接入我的资源');
    expect(Array.from(host.querySelectorAll('main button'), button => button.textContent)).not.toContain('查看我的资源');
    expect(text()).not.toContain('Checksum 是开发示例'); expect(host.querySelector('.or-development-card')).toBeNull();
    await click('高级与管理');
    await click('开发者装配');
    expect(host.querySelector('#application-selector')).not.toBeNull();
    expect(host.querySelector('nav')?.textContent).toContain('应用管理');
    expect(host.querySelector('.identity small')?.textContent).toBe('成员');
    expect(researchApi.autoresearch.start).not.toHaveBeenCalled();
  });
  it('enters OpenResearch from the catalog without a second application selector or controlled runner', async () => {
    vi.mocked(personalAgentApi.capabilities).mockResolvedValue({ executionContract: 'personal-external-v1', nativeQueue: true,
      ownerSubmit: '/api/factory/personal-agent/commands/submit', modelConfiguration: 'remote-configured-model', factoryBYOKForwarded: false });
    await render();
    expect(personalAgentApi.capabilities).not.toHaveBeenCalled();
    expect(applicationEnvironmentApi.capabilities).not.toHaveBeenCalled();
    await click('进入 OpenResearch');
    expect(window.location.search).toContain('tab=openresearch');
    expect(host.querySelector('h1')?.textContent).toBe('OpenResearch');
    expect(personalAgentApi.capabilities).toHaveBeenCalled();
    expect(host.querySelector('[role="alert"]')).toBeNull();
    expect(host.querySelector('#application-selector')).toBeNull();
    expect(host.querySelector('#autoresearch-title')).toBeNull();
    expect(openresearchApi.projects).not.toHaveBeenCalled();
    expect(api.applications).not.toHaveBeenCalled();
    await click('Factory 应用目录');
    expect(window.location.search).toContain('tab=catalog');
    expect(host.querySelector('h1')?.textContent).toBe('应用目录');
    expect(host.querySelector('.openresearch-workspace')).toBeNull();
    expect(personalAgentApi.prepare).not.toHaveBeenCalled();
    expect(personalAgentApi.submit).not.toHaveBeenCalled();
    expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled();
    expect(researchApi.autoresearch.start).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });
  it('keeps resources in their own navigation entry rather than an application card', async () => {
    await render();
    const resources = Array.from(host.querySelectorAll('nav button')).find(button => button.textContent === '资源');
    expect(resources).toBeTruthy();
    expect(Array.from(host.querySelectorAll('main h2'), heading => heading.textContent)).toEqual(['OpenResearch']);
    await click('资源');
    expect(window.location.search).toContain('tab=resources');
    expect(host.querySelector('h1')?.textContent).toBe('我的资源');
    expect(resources?.getAttribute('aria-current')).toBe('page');
    expect(text()).toContain('设置我的模型/API');
    expect(text()).toContain('管理服务器与连接');
    expect(personalAgentApi.capabilities).not.toHaveBeenCalled();
    expect(ownerModelApi.list).not.toHaveBeenCalled();
    await click('应用');
    expect(window.location.search).toContain('tab=catalog');
    expect(host.querySelector('h1')?.textContent).toBe('应用目录');
    expect(personalAgentApi.prepare).not.toHaveBeenCalled();
    expect(personalAgentApi.submit).not.toHaveBeenCalled();
    expect(researchApi.autoresearch.start).not.toHaveBeenCalled();
  });
  it('restores the selected application and catalog with browser Back and Forward without starting work', async () => {
    await render();
    await click('进入 OpenResearch');
    await click('Factory 应用目录');
    const length = window.history.length;
    await act(async () => { window.history.back(); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(window.location.search).toContain('tab=openresearch');
    expect(host.querySelector('h1')?.textContent).toBe('OpenResearch');
    expect(window.history.length).toBe(length);
    await act(async () => { window.history.back(); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(window.location.search).toContain('tab=catalog');
    expect(host.querySelector('h1')?.textContent).toBe('应用目录');
    await act(async () => { window.history.forward(); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(window.location.search).toContain('tab=openresearch');
    expect(host.querySelector('h1')?.textContent).toBe('OpenResearch');
    await act(async () => { window.history.forward(); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(window.location.search).toContain('tab=catalog');
    expect(host.querySelector('h1')?.textContent).toBe('应用目录');
    expect(window.history.length).toBe(length);
    expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled();
    expect(personalAgentApi.prepare).not.toHaveBeenCalled();
    expect(personalAgentApi.submit).not.toHaveBeenCalled();
    expect(researchApi.autoresearch.start).not.toHaveBeenCalled();
  });
  it('navigates to empty experimental runner and back via its actionable alternative', async () => {
    await render(); await click('开发者装配'); await click('打开受控 Auto-Research 实验');
    expect(window.location.search).toContain('tab=autoresearch');
    expect(text()).toContain('选择其他应用');
    await click('选择其他应用');
    expect(host.querySelector('#application-selector')).toBeNull();
    expect(window.location.search).toContain('tab=catalog');
    expect(researchApi.autoresearch.start).not.toHaveBeenCalled();
  });
  it('restores a task deep link after remount and responds to Back/Forward history events without creating work', async () => {
    window.history.replaceState(null, '', '/?tab=research&task=task-one'); await render();
    expect(api.detail).toHaveBeenCalledWith('task-one', expect.any(AbortSignal));
    expect(text()).toContain('任务不存在或无权访问');
    await click('应用');
    await act(async () => { window.history.back(); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(host.querySelector('h1')?.textContent).toBe('任务与证据');
    await act(async () => { window.history.forward(); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(host.querySelector('h1')?.textContent).toBe('应用目录');
    const href = window.location.href;
    await act(async () => root.unmount()); root = createRoot(host); await render();
    expect(window.location.href).toBe(href); expect(host.querySelector('h1')?.textContent).toBe('应用目录');
    expect(researchApi.autoresearch.start).not.toHaveBeenCalled();
  });
  it('keeps Back and Forward usable after a created research run and passive recovery', async () => {
    const preset = { id: 'preset-one', name: '受管研究', defaultGoal: '合成目标', ready: true, blockers: [], limits: { maxExperiments: 1 } };
    const record = { id: 'run-one', ownerId: 'alice', requestId: 'request-one', presetId: preset.id, goal: preset.defaultGoal, status: 'completed', steps: [], evidence: [], allowedActions: [], acceptance: { modelExecuted: false, instructionsRead: false, agentDecision: false, managedExperiment: false, independentResult: false, nextDecision: false, scientificConclusionVerified: false } };
    vi.mocked(researchApi.autoresearch.presets).mockResolvedValue([preset]);
    vi.mocked(researchApi.autoresearch.start).mockImplementation(async body => ({ ...record, requestId: body.requestId }));
    vi.mocked(researchApi.autoresearch.get).mockImplementation(async () => ({ ...record, requestId: vi.mocked(researchApi.autoresearch.start).mock.calls[0]?.[0].requestId ?? record.requestId }));
    vi.mocked(researchApi.autoresearch.recover).mockImplementation(async requestId => ({ ...record, requestId }));
    await render(); await click('开发者装配'); await click('打开受控 Auto-Research 实验'); await click('检查默认目标'); await click('确认并开始研究');
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(window.location.search).toContain('run=run-one');
    const length = window.history.length;
    await act(async () => { window.history.back(); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(window.history.length).toBe(length);
    await act(async () => { window.history.back(); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(host.querySelector('h1')?.textContent).toBe('开发者装配');
    await act(async () => { window.history.forward(); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(host.querySelector('#autoresearch-title')).not.toBeNull();
    expect(researchApi.autoresearch.start).toHaveBeenCalledTimes(1);
  });
  it('opens shared publication for members and labels only actual administrators', async () => {
    window.history.replaceState(null, '', '/?tab=applications'); await render();
    expect(window.location.search).toContain('tab=applications');
    expect(text()).toContain('应用管理内容');
    expect(host.querySelector('nav')?.textContent).toContain('共享应用与材料');
    expect(host.querySelector('.identity small')?.textContent).toBe('成员');
    await act(async () => root.unmount()); root = createRoot(host);
    window.history.replaceState(null, '', '/?tab=applications');
    const manager: User = { id: 'manager', name: 'Manager', role: 'manager' }; vi.mocked(api.session).mockResolvedValue(manager);
    await render(manager); expect(text()).toContain('应用管理内容');
    expect(host.querySelector('.identity small')?.textContent).toBe('账号管理员');
  });
});
