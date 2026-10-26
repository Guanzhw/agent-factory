// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApplicationCatalog, type InstalledApplication } from '../web/ApplicationCatalog.js';
import { Workspace } from '../web/App.js';
import { api } from '../web/api.js';
import { defaultNavigation } from '../web/workspaceNavigation.js';

vi.mock('../web/api.js', async importOriginal => {
  const original = await importOriginal<typeof import('../web/api.js')>();
  return { ...original, api: { ...original.api, status: vi.fn(), materials: vi.fn(), jobs: vi.fn(), executionTargets: vi.fn() } };
});

const notes: InstalledApplication = {
  id: 'synthetic-notes-fixture', name: '合成便笺', description: '整理离线合成便笺。',
  entry: { tab: 'synthetic-notes' },
};
const checking: InstalledApplication = {
  id: 'synthetic-checking-fixture', name: '合成校对', description: '校对离线合成样本。',
  entry: { tab: 'synthetic-checking' },
};
let host: HTMLDivElement;
let root: Root;
const onSelect = vi.fn<(entry: InstalledApplication['entry']) => void>();
const fetch = vi.fn(() => Promise.reject(new Error('Network is forbidden in the catalog fixture')));

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal('fetch', fetch);
  window.history.replaceState(null, '', '/?tab=catalog');
  vi.mocked(api.status).mockResolvedValue({ mode: 'demo', activeWorkers: 0, queuedJobs: 0, maxWorkers: 2, integration: 'Synthetic offline fixture', liveEnabled: false });
  vi.mocked(api.materials).mockResolvedValue([]); vi.mocked(api.jobs).mockResolvedValue({ items: [], nextCursor: null }); vi.mocked(api.executionTargets).mockResolvedValue([]);
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove(); vi.unstubAllGlobals();
});
async function render(applications: readonly InstalledApplication[]) {
  await act(async () => root.render(createElement(ApplicationCatalog, { applications, onSelect })));
}
async function select(name: string) {
  const button = Array.from(host.querySelectorAll('button')).find(value => value.textContent === `进入 ${name}`);
  expect(button).toBeTruthy();
  await act(async () => button!.click());
}

it('renders an empty catalog without inventing an application or selecting an entry', async () => {
  await render([]);
  expect(host.querySelector('h1')?.textContent).toBe('应用');
  expect(host.textContent).toContain('选择应用，开始工作。');
  expect(host.querySelectorAll('button')).toHaveLength(0);
  expect(onSelect).not.toHaveBeenCalled();
  expect(fetch).not.toHaveBeenCalled();
});

it('renders the installed application and selects its declared entry only on click', async () => {
  await render([notes]);
  expect(Array.from(host.querySelectorAll('h2'), heading => heading.textContent)).toEqual([notes.name]);
  expect(host.textContent).toContain(notes.description);
  expect(host.querySelectorAll('button')).toHaveLength(1);
  expect(onSelect).not.toHaveBeenCalled();
  await select(notes.name);
  expect(onSelect).toHaveBeenCalledExactlyOnceWith({ tab: 'synthetic-notes' });
  expect(fetch).not.toHaveBeenCalled();
});

it('supports a second synthetic application with its own declared navigation payload', async () => {
  await render([notes, checking]);
  expect(Array.from(host.querySelectorAll('h2'), heading => heading.textContent)).toEqual([notes.name, checking.name]);
  expect(host.textContent).toContain(checking.description);
  expect(host.querySelectorAll('button')).toHaveLength(2);
  await select(checking.name);
  await select(notes.name);
  expect(onSelect.mock.calls).toEqual([[{ tab: 'synthetic-checking' }], [{ tab: 'synthetic-notes' }]]);
  expect(fetch).not.toHaveBeenCalled();
});

it('registers a second application in test composition and restores its entry through browser history', async () => {
  const applications = [notes, checking] as const;
  const navigation = { ...defaultNavigation,
    tabs: { ...defaultNavigation.tabs, ...Object.fromEntries(applications.map(application => [application.entry.tab, application.name])) },
    applicationTabs: applications.map(application => application.entry.tab),
  };
  function SyntheticComposition() {
    return createElement(Workspace, {
      user: { id: 'synthetic-member', name: '合成成员', role: 'user' },
      logout: () => {}, sessionBusy: false, sessionError: '', navigation,
      children: ({ route, navigate }) => {
        if (route.tab === 'catalog') return createElement(ApplicationCatalog, { applications, onSelect: navigate });
        const application = applications.find(value => value.entry.tab === route.tab);
        return application ? createElement('section', { 'data-synthetic-entry': application.id },
          createElement('h1', null, application.name),
          createElement('p', null, application.description),
          createElement('button', { onClick: () => navigate({ tab: 'catalog' }) }, '返回应用目录')) : null;
      },
    });
  }
  await act(async () => root.render(createElement(SyntheticComposition)));
  await select(checking.name);
  expect(new URL(window.location.href).searchParams.get('tab')).toBe(checking.entry.tab);
  expect(host.querySelector('h1')?.textContent).toBe(checking.name);
  expect(host.querySelector('[data-synthetic-entry]')?.getAttribute('data-synthetic-entry')).toBe(checking.id);
  const backToCatalog = Array.from(host.querySelectorAll('button')).find(button => button.textContent === '返回应用目录');
  expect(backToCatalog).toBeTruthy();
  await act(async () => backToCatalog!.click());
  expect(host.querySelector('h1')?.textContent).toBe('应用');
  expect(host.querySelector('[data-synthetic-entry]')).toBeNull();
  const length = window.history.length;
  await act(async () => { window.history.back(); await new Promise(resolve => setTimeout(resolve, 20)); });
  expect(new URL(window.location.href).searchParams.get('tab')).toBe(checking.entry.tab);
  expect(host.querySelector('h1')?.textContent).toBe(checking.name);
  await act(async () => { window.history.back(); await new Promise(resolve => setTimeout(resolve, 20)); });
  expect(host.querySelector('h1')?.textContent).toBe('应用');
  await act(async () => { window.history.forward(); await new Promise(resolve => setTimeout(resolve, 20)); });
  expect(host.querySelector('h1')?.textContent).toBe(checking.name);
  await act(async () => { window.history.forward(); await new Promise(resolve => setTimeout(resolve, 20)); });
  expect(host.querySelector('h1')?.textContent).toBe('应用');
  expect(window.history.length).toBe(length);
  expect(host.querySelector('[role="alert"]')).toBeNull();
  expect(fetch).not.toHaveBeenCalled();
});
