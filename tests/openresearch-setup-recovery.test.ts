// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { OpenResearchSetup } from '../web/OpenResearchSetup.js';
import { api, ApiError } from '../web/api.js';
import { personalRemoteApi, type PersonalRemote } from '../web/personalRemoteApi.js';
import { personalOrxProjectApi, type ProjectSelectionStatus } from '../web/personalOrxProjectApi.js';
import { ORX_PERSONAL_PROVIDER } from '../web/personalAgentApi.js';
import type { UserConnection } from '../web/models.js';
vi.mock('../web/PersonalRemotes.js', () => ({ PersonalRemotes: () => createElement('p', {}, 'Repair service fixture') }));
const owner = { id: 'setup-owner', name: 'Fixture', role: 'user' as const };
const pin = { ref: 'source', ownerId: owner.id, registrationRef: 'registration', kind: 'orx', available: true, status: 'active', taskId: null, capabilities: ['project:create', 'session:read'] } as UserConnection;
const storage = `factory-orx-project-selection:${owner.id}`;
let host: HTMLDivElement; let root: Root; const connected = vi.fn();
const button = (text: string) => [...host.querySelectorAll('button')].find(b => b.textContent === text)!;
async function mount() { await act(async () => root.render(createElement(OpenResearchSetup, { ownerId: owner.id, onConnected: connected }))); }
async function click(text: string) { await act(async () => button(text).click()); }
function receipt(requestId: string, values: Partial<ProjectSelectionStatus> = {}): ProjectSelectionStatus { return { requestId, ownerId: owner.id, state: 'failed', localConfiguration: 'none', failureStatus: 404, connection: null, ...values }; }
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto); localStorage.clear(); connected.mockReset();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  vi.spyOn(api, 'session').mockResolvedValue(owner); vi.spyOn(api, 'userConnections').mockResolvedValue([pin]);
  vi.spyOn(personalRemoteApi, 'list').mockResolvedValue([{ registrationRef: pin.registrationRef, providerId: ORX_PERSONAL_PROVIDER, origin: 'Synthetic service' } as PersonalRemote]);
  vi.spyOn(personalOrxProjectApi, 'existing').mockResolvedValue([{ nativeProjectId: 'project', name: 'Synthetic project', path: '/synthetic' }]);
  vi.spyOn(personalOrxProjectApi, 'selectExisting').mockRejectedValue(new ApiError('private details', 404));
  vi.spyOn(personalOrxProjectApi, 'recoverSelected').mockImplementation(async id => receipt(id));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it.each([403, 404, 409])('unlocks a known %s rejection while preserving its receipt and requiring a new explicit selection', async status => {
  vi.mocked(personalOrxProjectApi.recoverSelected).mockImplementation(async id => receipt(id, { failureStatus: status }));
  await mount(); await click('使用此项目'); const id = vi.mocked(personalOrxProjectApi.selectExisting).mock.calls[0][2];
  expect(localStorage.getItem(storage)).toBeNull(); expect(localStorage.getItem(storage + ':retained')).toContain(id);
  expect(host.textContent).toContain('没有启动研究'); expect(host.textContent).not.toContain('private details');
  expect(button('使用此项目').disabled).toBe(false); expect(personalOrxProjectApi.selectExisting).toHaveBeenCalledTimes(1);
  await click('使用此项目'); expect(vi.mocked(personalOrxProjectApi.selectExisting).mock.calls[1][2]).not.toBe(id);
});
it('restores a partial terminal failure after refresh and permits repair without replaying configuration', async () => {
  localStorage.setItem(storage, 'original-partial');
  vi.mocked(personalOrxProjectApi.recoverSelected).mockResolvedValue(receipt('original-partial', { localConfiguration: 'partial', failureStatus: 409 }));
  await mount(); await click('核对原连接');
  expect(host.textContent).toContain('部分本地配置已保存'); expect(button('使用此项目').disabled).toBe(false);
  expect(personalOrxProjectApi.selectExisting).not.toHaveBeenCalled(); expect(connected).not.toHaveBeenCalled();
});
it('retains unknown POST and a single GET 404 across refresh; leaving preserves evidence without replay', async () => {
  vi.mocked(personalOrxProjectApi.selectExisting).mockRejectedValue(new ApiError('offline', 0));
  vi.mocked(personalOrxProjectApi.recoverSelected).mockRejectedValue(new ApiError('absent', 404));
  await mount(); await click('使用此项目'); const id = vi.mocked(personalOrxProjectApi.selectExisting).mock.calls[0][2];
  expect(button('使用此项目').disabled).toBe(true); expect(localStorage.getItem(storage)).toBe(id);
  await act(async () => root.render(createElement('p'))); await mount(); await click('核对原连接');
  expect(host.textContent).toContain('单次未找到不能证明从未执行'); expect(button('使用此项目').disabled).toBe(true);
  await click('保留原记录，改用其他项目或连接');
  expect(localStorage.getItem(storage)).toBeNull(); expect(localStorage.getItem(storage + ':retained')).toContain(id);
  expect(host.textContent).toContain('原连接结果仍未知'); expect(button('使用此项目').disabled).toBe(false);
  expect(personalOrxProjectApi.selectExisting).toHaveBeenCalledTimes(1); expect(connected).not.toHaveBeenCalled();
  await act(async () => root.render(createElement('p'))); await mount(); expect(host.textContent).toContain(id);
});
it('shows partial unknown state without accepting a connection or replaying a POST', async () => {
  localStorage.setItem(storage, 'original-unknown');
  vi.mocked(personalOrxProjectApi.recoverSelected).mockResolvedValue(receipt('original-unknown', { state: 'unknown', failureStatus: null, localConfiguration: 'partial' }));
  await mount(); await click('核对原连接'); expect(host.textContent).toContain('最终结果仍未知');
  expect(button('使用此项目').disabled).toBe(true); expect(personalOrxProjectApi.selectExisting).not.toHaveBeenCalled(); expect(connected).not.toHaveBeenCalled();
});
it('adopts only the original completed binding read-only', async () => {
  localStorage.setItem(storage, 'original-complete');
  vi.mocked(personalOrxProjectApi.recoverSelected).mockResolvedValue(receipt('original-complete', { state: 'complete', failureStatus: null, connection: pin }));
  await mount(); await click('核对原连接'); expect(connected).toHaveBeenCalledWith(pin.ref);
  expect(personalOrxProjectApi.selectExisting).not.toHaveBeenCalled(); expect(localStorage.getItem(storage)).toBeNull();
});
it('does not unlock another owner or lose the only pending pointer when browser storage fails', async () => {
  localStorage.setItem(storage, 'retained-original'); await mount();
  vi.mocked(api.session).mockResolvedValue({ ...owner, id: 'other-owner' });
  await click('保留原记录，改用其他项目或连接'); expect(localStorage.getItem(storage)).toBe('retained-original');
  vi.mocked(api.session).mockResolvedValue(owner); await act(async () => root.render(createElement('p'))); await mount();
  vi.spyOn(localStorage, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
  await click('保留原记录，改用其他项目或连接'); expect(localStorage.getItem(storage)).toBe('retained-original');
  expect(button('使用此项目').disabled).toBe(true); expect(personalOrxProjectApi.selectExisting).not.toHaveBeenCalled();
});
