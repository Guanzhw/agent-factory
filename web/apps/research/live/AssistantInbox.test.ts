// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AssistantInbox } from './AssistantInbox.js';
import { assistantApi, type ResearchQuestion } from './assistantClient.js';
const question: ResearchQuestion = { id: 'q-a', senderId: 'alice', recipientId: 'bob', endpointId: 'qa-bob', text: '仅给Bob的问题', createdAt: '', delivery: { state: 'unconfirmed', taskId: null, runId: null }, reply: null };
let host: HTMLDivElement; let root: Root; const open = vi.fn(); const settings = vi.fn();
const button = (text: string) => [...host.querySelectorAll('button')].find(item => item.textContent === text)!;
beforeEach(() => { vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); host = document.createElement('div'); document.body.append(host); root = createRoot(host); open.mockReset(); settings.mockReset(); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount(owner = 'bob') { await act(async () => root.render(createElement(AssistantInbox, { key: owner, ownerId: owner, onQuestion: open, onSettings: settings }))); }
it('lists, refreshes and paginates original messages without starting or recovering them', async () => {
  const inbox = vi.spyOn(assistantApi, 'inbox').mockResolvedValue({ items: [question], nextCursor: 'q-a' }); const recover = vi.spyOn(assistantApi, 'recover');
  await mount(); await act(async () => button(question.text).click()); expect(open).toHaveBeenCalledWith(question.id);
  await act(async () => button('下一页收件').click()); expect(inbox).toHaveBeenLastCalledWith('bob', 'q-a', expect.any(AbortSignal));
  await act(async () => button('刷新收到的问题').click()); await act(async () => button('设置我的助手').click());
  expect(settings).toHaveBeenCalledOnce(); expect(recover).not.toHaveBeenCalled();
});
it('does not show a late old-owner inbox or disguise a read error as an empty list', async () => {
  let finish!: (value: { items: ResearchQuestion[]; nextCursor: null }) => void;
  vi.spyOn(assistantApi, 'inbox').mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })).mockRejectedValue(new Error('收件暂时不可读'));
  await mount(); await mount('carol'); await act(async () => finish({ items: [question], nextCursor: null }));
  expect(host.textContent).not.toContain(question.text); expect(host.textContent).toContain('收件暂时不可读'); expect(host.textContent).not.toContain('本页尚无收到的问题');
});
