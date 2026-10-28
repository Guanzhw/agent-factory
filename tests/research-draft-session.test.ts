// @vitest-environment happy-dom
import { act, createElement, StrictMode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ResearchApp from '../web/research-composition.js';
import { api, ApiError } from '../web/api.js';
import * as auth from '../web/browserAuth.js';
import { ownerModelApi } from '../web/ownerModelApi.js';
import { researchApi } from '../web/apps/research/client.js';
import { assistantApi } from '../web/apps/research/live/assistantClient.js';
import { researchSessionsApi } from '../web/apps/research/researchSessionsClient.js';
import { draftKey, requestKey } from '../web/apps/research/researchSessionStorage.js';

let host: HTMLDivElement; let root: Root;
const draft = { title: '需要保留的研究', goal: '私人研究草稿', boundaries: '完成后停止', modelConnectionRef: '', limits: { maxTurns: 8, toolCallsPerTurn: 8, operationSeconds: 8 } };
const button = (text: string) => [...host.querySelectorAll('button')].find(item => item.textContent === text)!;
async function mount() { await act(async () => root.render(createElement(StrictMode, null, createElement(ResearchApp)))); }
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); window.sessionStorage.clear();
  window.history.replaceState(null, '', '/?tab=research&researchView=sessions');
  const config = auth.configureBrowserAuth({ enabled: true, oidcEnabled: false, localLoginEnabled: true, loginPath: '/api/factory/auth/login', logoutPath: '/api/factory/auth/logout' });
  vi.spyOn(auth, 'browserAuthConfig').mockResolvedValue(config);
  vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() } as unknown as MediaQueryList);
  vi.spyOn(api, 'session').mockResolvedValue({ id: 'alice', name: 'Alice', role: 'user' });
  vi.spyOn(api, 'logout').mockResolvedValue(undefined);
  vi.spyOn(api, 'status').mockRejectedValue(new Error('Status unavailable in this isolated test'));
  vi.spyOn(api, 'materials').mockResolvedValue([]); vi.spyOn(api, 'executionTargets').mockResolvedValue([]); vi.spyOn(api, 'jobs').mockResolvedValue({ items: [], nextCursor: null });
  vi.spyOn(researchApi, 'projects').mockResolvedValue({ items: [], nextCursor: null });
  vi.spyOn(assistantApi, 'me').mockResolvedValue({ assistant: null });
  vi.spyOn(researchSessionsApi, 'options').mockResolvedValue({ available: false, unavailableCode: 'RESEARCH_MODEL_REQUIRED', models: [], limits: { maxTurns: { min: 1, max: 20, default: 8 }, toolCallsPerTurn: { min: 1, max: 8, default: 8 }, operationSeconds: { min: 1, max: 30, default: 8 }, contextCharacters: 12000 }, workspace: { configured: true, hostCommands: true, isolation: 'host-user-not-os-sandbox' }, accounting: { tokenMetered: false, costMetered: false } });
  vi.spyOn(researchSessionsApi, 'list').mockResolvedValue({ items: [], nextCursor: null });
  vi.spyOn(ownerModelApi, 'capabilities').mockRejectedValue(new Error('No model configuration in this isolated test'));
  vi.spyOn(ownerModelApi, 'list').mockResolvedValue([]);
  window.sessionStorage.setItem(draftKey('alice'), JSON.stringify(draft));
  window.sessionStorage.setItem(requestKey('alice'), JSON.stringify([{ requestId: 'old-request', action: 'turn', sessionId: 'old-session' }]));
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('preserves an existing draft under StrictMode through the real model page and back', async () => {
  await mount(); expect(window.sessionStorage.getItem(draftKey('alice'))).toContain('私人研究草稿');
  await act(async () => button('配置我的模型').click()); expect(window.location.search).toContain('tab=models');
  const back = [...host.querySelectorAll('button')].find(item => item.textContent?.includes('返回'))!;
  await act(async () => back.click());
  expect(window.location.search).toContain('researchView=sessions');
  expect((host.querySelector('textarea') as HTMLTextAreaElement).value).toBe('私人研究草稿');
});

it('keeps text when logout fails and clears only the old owner draft after confirmed logout', async () => {
  vi.mocked(api.logout).mockRejectedValueOnce(new ApiError('退出尚未确认', 503));
  window.sessionStorage.setItem(draftKey('bob'), JSON.stringify({ ...draft, goal: 'Bob 的草稿' }));
  await mount(); await act(async () => (host.querySelector('.rw-identity > button') as HTMLButtonElement).click());
  await act(async () => button('退出登录').click());
  expect(host.textContent).toContain('退出尚未确认'); expect(window.sessionStorage.getItem(draftKey('alice'))).toContain('私人研究草稿');
  await act(async () => button('退出登录').click());
  expect(button('登录')).toBeDefined(); expect(window.sessionStorage.getItem(draftKey('alice'))).toBeNull();
  expect(window.sessionStorage.getItem(draftKey('bob'))).toContain('Bob 的草稿');
  expect(window.sessionStorage.getItem(requestKey('alice'))).toContain('old-request');
});

it('clears an expired identity draft before entering another owner while retaining that owner draft', async () => {
  window.sessionStorage.setItem(draftKey('bob'), JSON.stringify({ ...draft, goal: 'Bob 的草稿' }));
  await mount(); await act(async () => auth.expireBrowserSession());
  expect(window.sessionStorage.getItem(draftKey('alice'))).toBeNull();
  await act(async () => root.unmount()); root = createRoot(host);
  vi.mocked(api.session).mockResolvedValue({ id: 'bob', name: 'Bob', role: 'user' });
  await mount(); expect((host.querySelector('textarea') as HTMLTextAreaElement).value).toBe('Bob 的草稿');
  expect(window.sessionStorage.getItem(draftKey('bob'))).toContain('Bob 的草稿');
});
