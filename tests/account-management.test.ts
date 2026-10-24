// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AccountManagement } from '../web/AccountManagement.js';
import { accountApi } from '../web/accountApi.js';

let host: HTMLDivElement; let root: Root;
const member = { id: 'alice', name: 'Alice', email: null, disabled: true, accountAdmin: false };
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  vi.spyOn(accountApi, 'list').mockResolvedValue({ accounts: [member], total: 1 });
  vi.spyOn(accountApi, 'update').mockResolvedValue(member);
  vi.spyOn(accountApi, 'create').mockResolvedValue({ ...member, id: 'bob', disabled: false });
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const button = (text: string) => [...host.querySelectorAll('button')].find(item => item.textContent === text)!;
async function mount() { await act(async () => root.render(createElement(AccountManagement))); }
async function field(label: string, value: string) {
  const input = host.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!;
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })); });
}
it('keeps name edits separate from account activation and administrator assignment', async () => {
  await mount(); expect(host.textContent).toContain('已停用');
  await field('alice 姓名', 'Alice Renamed');
  await act(async () => button('保存账号信息').click());
  expect(accountApi.update).toHaveBeenLastCalledWith('alice', { name: 'Alice Renamed' });
  await act(async () => button('启用账号').click());
  expect(accountApi.update).toHaveBeenLastCalledWith('alice', { disabled: false });
  await act(async () => button('设为账号管理员').click());
  expect(accountApi.update).toHaveBeenLastCalledWith('alice', { accountAdmin: true });
});
it('creates a member account with the explicit identifier and reports failures', async () => {
  await mount(); await field('账号标识', 'bob'); await field('新账号姓名', 'Bob');
  await act(async () => button('新增账号').click());
  expect(accountApi.create).toHaveBeenCalledWith({ id: 'bob', name: 'Bob', email: undefined, accountAdmin: false });
  vi.mocked(accountApi.update).mockRejectedValueOnce(new Error('Account administrator required'));
  await act(async () => button('启用账号').click());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain('Account administrator required');
});
