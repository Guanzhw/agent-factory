// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ResearchDemo } from '../web/apps/research-demo/ResearchDemo.js';

vi.mock('../web/apps/research-demo/MetricsChart.js', () => ({ MetricsChart: () => createElement('div', null, 'Synthetic chart fixture') }));
let host: HTMLDivElement; let root: Root;
const logout = vi.fn(); const navigate = vi.fn(); const fetch = vi.fn();
beforeEach(() => {
  vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() } as unknown as MediaQueryList);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('fetch', fetch); window.sessionStorage.clear();
  logout.mockReset(); navigate.mockReset(); fetch.mockReset();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const button = (text: string) => [...host.querySelectorAll('button')].find(item => item.textContent === text)!;
async function render(sessionBusy = false, sessionError = '', project = 'inference') {
  await act(async () => root.render(createElement(ResearchDemo, { user: { id: 'alice', name: 'Alice', role: 'user' }, route: { tab: 'research', task: '', project }, navigate, onLogout: logout, sessionBusy, sessionError })));
}
it('shows the existing session error and disables logout while the platform session is busy', async () => {
  await render(true, '退出失败，请重试');
  await act(async () => (host.querySelector('.rd-identity > button') as HTMLButtonElement).click());
  expect(host.querySelector('[role="alert"]')?.textContent).toBe('退出失败，请重试');
  expect(button('正在退出…').disabled).toBe(true);
  await act(async () => button('正在退出…').click()); expect(logout).not.toHaveBeenCalled();
  await render(false, '退出失败，请重试'); await act(async () => button('退出登录').click());
  expect(logout).toHaveBeenCalledOnce(); expect(fetch).not.toHaveBeenCalled();
});
it('resets discussion for the current project without importing inference results', async () => {
  await render(false, '', 'augmentation');
  await act(async () => (host.querySelector('[aria-label="助手选项"]') as HTMLButtonElement).click());
  await act(async () => button('重置演示对话').click());
  expect(host.querySelector('.rd-messages')?.textContent).toContain('当前项目的演示讨论');
  expect(host.querySelector('.rd-messages')?.textContent).not.toContain('实验12已运行完成');
});
it('marks only application resource navigation and clears that origin on explicit platform return', async () => {
  await render(); await act(async () => button('资源').click());
  expect(navigate).toHaveBeenLastCalledWith(expect.objectContaining({ tab: 'resources', modelReturn: 'research' }));
  await act(async () => button('返回平台').click());
  expect(navigate).toHaveBeenLastCalledWith(expect.objectContaining({ tab: 'catalog', modelReturn: '', project: '' }));
});
