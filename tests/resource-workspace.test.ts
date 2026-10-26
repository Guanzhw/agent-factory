// @vitest-environment happy-dom
import { act, createElement, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConnectionsPanel } from '../web/ConnectionsPanel.js';
import { ResourceCenter } from '../web/ResourceCenter.js';
import { ResourceNavigation } from '../web/ResourceNavigation.js';
import { PersonalRemotes } from '../web/PersonalRemotes.js';
import type { ResourceSection } from '../web/workspaceNavigation.js';
import { api } from '../web/api.js';
import { personalSSHApi } from '../web/personalSSHApi.js';
import { personalRemoteApi } from '../web/personalRemoteApi.js';
import { personalToolConnectionApi } from '../web/personalToolConnectionApi.js';

const user = { id: 'resource-owner', name: 'Resource Owner', role: 'user' as const };
let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); localStorage.clear();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  vi.spyOn(api, 'session').mockResolvedValue(user);
  vi.spyOn(api, 'userConnections').mockResolvedValue([]);
  vi.spyOn(api, 'connectionRegistrations').mockResolvedValue([]);
  vi.spyOn(api, 'resourceLeases').mockResolvedValue({ leases: [], nextCursor: null });
  vi.spyOn(personalSSHApi, 'capabilities').mockResolvedValue({ enabled: false });
  vi.spyOn(personalSSHApi, 'list').mockResolvedValue([]);
  vi.spyOn(personalRemoteApi, 'credentialAvailability').mockResolvedValue({ enabled: false, providerIds: [] });
  vi.spyOn(personalRemoteApi, 'credentials').mockResolvedValue([]);
  vi.spyOn(personalRemoteApi, 'providers').mockResolvedValue([]);
  vi.spyOn(personalRemoteApi, 'list').mockResolvedValue([]);
  vi.spyOn(personalToolConnectionApi, 'descriptors').mockResolvedValue([]);
  vi.spyOn(personalToolConnectionApi, 'list').mockResolvedValue([]);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const button = (label: string) => [...host.querySelectorAll('button')].find(value => value.textContent === label)!;
function ResourcePages({ initial = 'servers' }: { initial?: ResourceSection }) {
  const [section, setSection] = useState<ResourceSection>(initial);
  return createElement(ConnectionsPanel, { user, jobs: [], busy: '', section,
    act: async (_name, work) => work(), onNotice: vi.fn(),
    navigation: createElement(ResourceNavigation, { active: section, onModels: vi.fn(), onConnections: setSection }),
    remoteServices: (_refresh, onChanged) => createElement(PersonalRemotes, { user, jobs: [], onChanged }),
  });
}
it('offers each existing resource purpose without creating resources', async () => {
  const models = vi.fn(); const connections = vi.fn(); const back = vi.fn();
  await act(async () => root.render(createElement(ResourceCenter, { onModels: models, onConnections: connections, onBack: back, applicationLabel: 'AutoResearch' })));
  for (const [label, section] of [['管理服务器', 'servers'], ['管理工具', 'tools'], ['管理凭据', 'credentials'], ['管理远程服务', 'remotes'], ['查看高级记录', 'advanced']]) {
    await act(async () => button(label).click()); expect(connections).toHaveBeenLastCalledWith(section);
  }
  await act(async () => button('设置模型').click()); expect(models).toHaveBeenCalledTimes(1);
  await act(async () => button('返回 AutoResearch').click()); expect(back).toHaveBeenCalledTimes(1);
  expect(api.userConnections).not.toHaveBeenCalled(); expect(personalSSHApi.capabilities).not.toHaveBeenCalled();
});
it('loads only visited resource categories and stops advanced polling when leaving it', async () => {
  await act(async () => root.render(createElement(ResourcePages)));
  expect(personalSSHApi.capabilities).toHaveBeenCalledTimes(1);
  expect(personalSSHApi.list).not.toHaveBeenCalled();
  expect(personalRemoteApi.credentialAvailability).not.toHaveBeenCalled(); expect(personalToolConnectionApi.descriptors).not.toHaveBeenCalled(); expect(api.resourceLeases).not.toHaveBeenCalled();
  expect(button('服务器').getAttribute('aria-current')).toBe('page');
  await act(async () => button('高级记录').click());
  expect(api.userConnections).toHaveBeenCalledTimes(1); expect(api.resourceLeases).toHaveBeenCalledTimes(1);
  const connectionSignal = vi.mocked(api.userConnections).mock.calls[0][0]!;
  expect(host.querySelector('[data-resource-section="servers"]')?.hasAttribute('hidden')).toBe(true);
  expect(host.textContent).toContain('我的连接引用'); expect(host.textContent).toContain('我的执行租约');
  expect(host.textContent).not.toContain('合成演示');
  await act(async () => button('工具').click());
  expect(connectionSignal.aborted).toBe(true); expect(personalToolConnectionApi.descriptors).toHaveBeenCalledTimes(1);
  expect(button('工具').getAttribute('aria-current')).toBe('page');
  expect(host.querySelector('[data-resource-section="advanced"]')?.hasAttribute('hidden')).toBe(true);
  await act(async () => button('高级记录').click()); expect(api.userConnections).toHaveBeenCalledTimes(2);
});
it('keeps an unknown remote credential reachable across category changes without replay', async () => {
  const storage = `factory-credential-pending:${user.id}`; localStorage.setItem(storage, 'original-remote-credential');
  const recovery = vi.spyOn(personalRemoteApi, 'recoverCredential').mockRejectedValue(new Error('not yet confirmed'));
  const save = vi.spyOn(personalRemoteApi, 'saveCredential'); const configure = vi.spyOn(personalRemoteApi, 'configure');
  await act(async () => root.render(createElement(ResourcePages, { initial: 'remotes' })));
  const original = host.querySelector('[aria-label="原远程凭据核对"]'); expect(original).not.toBeNull();
  expect(recovery).not.toHaveBeenCalled();
  await act(async () => button('凭据').click());
  expect(host.querySelector('[data-resource-section="remotes"]')?.hasAttribute('hidden')).toBe(true);
  expect(localStorage.getItem(storage)).toBe('original-remote-credential');
  await act(async () => button('远程服务').click());
  expect(host.querySelector('[aria-label="原远程凭据核对"]')).toBe(original);
  await act(async () => button('核对原凭据请求').click());
  expect(recovery).toHaveBeenCalledExactlyOnceWith('original-remote-credential', user.id);
  expect(localStorage.getItem(storage)).toBe('original-remote-credential'); expect(save).not.toHaveBeenCalled(); expect(configure).not.toHaveBeenCalled();
});
