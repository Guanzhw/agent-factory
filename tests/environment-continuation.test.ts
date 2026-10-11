// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api, ApiError } from '../web/api.js';
import { EnvironmentContinuation } from '../web/EnvironmentContinuation.js';
import { applicationEnvironmentApi, type ApplicationEnvironment, type EnvironmentContinuation as Preview } from '../web/applicationEnvironmentApi.js';

const owner = { id: 'synthetic-owner', name: 'Fixture', role: 'user' as const };
const environment: ApplicationEnvironment = { id: 'original-environment', projectId: 'original-project', applicationId: 'openresearch',
  location: 'platform', state: 'stopped', packageVersion: 'fixed-fixture', connectionRef: 'original-connection',
  modelReference: 'original-model', modelRevision: 'original-model-revision', dataRetained: true, researchSubmitted: false };
const preview: Preview = { environmentId: environment.id, projectId: environment.projectId, dataRetained: true,
  classification: 'can-continue', canRebind: true, requiresCredentialRebind: true, sessionRebindRequired: true,
  previewHash: 'a'.repeat(64), originalWorkReplay: false, researchSubmitted: false, nativeCheckpointContinuationVerified: false,
  reason: 'ENVIRONMENT_EXPLICIT_BINDING_REQUIRED', nextAction: 'rebind-credentials', message: '原环境已停止；请确认新绑定。',
  currentModelChoice: { reference: 'current-model', revision: 'current-revision', name: 'Explicit current model', provider: 'openai-compatible', endpoint: 'https://models.example.com/v1' } };
const receipt = (requestId: string) => ({ requestId, state: 'committed' as const,
  environment: { ...environment, modelRevision: 'verified-model-revision' }, runtimePrepared: false as const, researchSubmitted: false as const });
let host: HTMLDivElement; let root: Root;
const changed = vi.fn(); const pending = vi.fn(); const newEnvironment = vi.fn();
const storage = `factory-environment-binding:${owner.id}:${environment.id}`;
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto); localStorage.clear();
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host);
  changed.mockReset(); pending.mockReset(); newEnvironment.mockReset();
  vi.spyOn(api, 'session').mockResolvedValue(owner);
  vi.spyOn(applicationEnvironmentApi, 'continuation').mockResolvedValue(preview);
  vi.spyOn(applicationEnvironmentApi, 'rebind').mockImplementation(async (_owner, _env, requestId) => receipt(requestId));
  vi.spyOn(applicationEnvironmentApi, 'bindingRequest').mockImplementation(async (_owner, requestId) => receipt(requestId));
  vi.spyOn(applicationEnvironmentApi, 'prepare'); vi.spyOn(applicationEnvironmentApi, 'stop');
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount(ownerId = owner.id) { await act(async () => root.render(createElement(EnvironmentContinuation, {
  ownerId, environment, disabled: false, onPending: pending, onChanged: changed, onNewEnvironment: newEnvironment,
}))); }
function button(label: string) { const item = [...host.querySelectorAll('button')].find(b => b.textContent === label); if (!item) throw new Error(label); return item; }
async function click(label: string) { await act(async () => button(label).click()); }
async function inspect() { await mount(); await click('核对恢复条件'); }

it('reads first, commits once after fresh consent, and does not restore or submit work', async () => {
  await inspect(); expect(applicationEnvironmentApi.rebind).not.toHaveBeenCalled();
  expect(host.textContent).toContain('Explicit current model'); expect(host.textContent).toContain('https://models.example.com/v1');
  await act(async () => { button('确认新凭据绑定').click(); button('确认新凭据绑定').click(); });
  expect(applicationEnvironmentApi.continuation).toHaveBeenCalledTimes(2);
  expect(applicationEnvironmentApi.rebind).toHaveBeenCalledTimes(1);
  expect(applicationEnvironmentApi.rebind).toHaveBeenCalledWith(owner.id, environment.id, expect.any(String), preview.previewHash);
  expect(changed).toHaveBeenCalledWith(expect.objectContaining({ id: environment.id, projectId: environment.projectId }));
  expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled(); expect(applicationEnvironmentApi.stop).not.toHaveBeenCalled();
  expect(localStorage.getItem(storage)).toBeNull(); expect(host.textContent).toContain('此请求未恢复环境或发送目标');
});
it('requires new consent when the reviewed credential selection changes before the write', async () => {
  await inspect(); vi.mocked(applicationEnvironmentApi.continuation).mockResolvedValue({ ...preview, previewHash: 'b'.repeat(64) });
  await click('确认新凭据绑定'); expect(applicationEnvironmentApi.rebind).not.toHaveBeenCalled();
  expect(localStorage.getItem(storage)).toBeNull(); expect(host.textContent).toContain('恢复条件已变化');
});
it('recovers a lost acknowledgement after reload through GET of the original request only', async () => {
  vi.mocked(applicationEnvironmentApi.rebind).mockRejectedValue(new Error('untrusted detail'));
  await inspect(); await click('确认新凭据绑定'); const original = JSON.parse(localStorage.getItem(storage)!);
  expect(host.textContent).not.toContain('untrusted detail');
  await act(async () => root.unmount()); root = createRoot(host); await mount();
  expect(pending).toHaveBeenLastCalledWith(true);
  await act(async () => { button('核对原绑定请求').click(); button('核对原绑定请求').click(); });
  expect(applicationEnvironmentApi.bindingRequest).toHaveBeenCalledTimes(1);
  expect(applicationEnvironmentApi.bindingRequest).toHaveBeenCalledWith(owner.id, original.requestId);
  expect(applicationEnvironmentApi.rebind).toHaveBeenCalledTimes(1); expect(localStorage.getItem(storage)).toBeNull();
});
it('keeps an unknown request locked when its receipt is absent instead of creating another request', async () => {
  vi.mocked(applicationEnvironmentApi.rebind).mockRejectedValue(new Error('lost acknowledgement'));
  await inspect(); await click('确认新凭据绑定'); const original = localStorage.getItem(storage);
  vi.mocked(applicationEnvironmentApi.bindingRequest).mockRejectedValue(new ApiError('ENVIRONMENT_BINDING_REQUEST_NOT_FOUND', 404));
  await click('核对原绑定请求'); expect(localStorage.getItem(storage)).toBe(original);
  expect(applicationEnvironmentApi.rebind).toHaveBeenCalledTimes(1); expect(changed).not.toHaveBeenCalled();
});
it('allows fresh review after a positively rejected pre-commit preview, without automatic retry', async () => {
  vi.mocked(applicationEnvironmentApi.rebind).mockRejectedValue(new ApiError('ENVIRONMENT_BINDING_PREVIEW_CHANGED', 409, 'REQUEST_REJECTED'));
  await inspect(); await click('确认新凭据绑定'); expect(localStorage.getItem(storage)).toBeNull();
  expect(host.textContent).toContain('新绑定未保存'); expect(applicationEnvironmentApi.rebind).toHaveBeenCalledTimes(1);
  expect(button('核对恢复条件').disabled).toBe(false);
});
it('rejects a receipt that replaces native project identity and keeps original recovery custody', async () => {
  vi.mocked(applicationEnvironmentApi.rebind).mockImplementation(async (_owner, _env, requestId) => ({ ...receipt(requestId), environment: { ...environment, projectId: 'replacement-project' } }));
  await inspect(); await click('确认新凭据绑定'); expect(changed).not.toHaveBeenCalled();
  expect(localStorage.getItem(storage)).not.toBeNull(); expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled();
});
it('does not write after an account change or insufficient durable request storage', async () => {
  await inspect(); vi.mocked(api.session).mockResolvedValue({ ...owner, id: 'different-owner' });
  await click('确认新凭据绑定'); expect(applicationEnvironmentApi.rebind).not.toHaveBeenCalled();
  vi.mocked(api.session).mockResolvedValue(owner);
  const original = localStorage;
  vi.stubGlobal('localStorage', new Proxy(original, { get(target, key) { return key === 'setItem' ? () => { throw new Error('denied'); } : Reflect.get(target, key); } }));
  await click('确认新凭据绑定'); expect(applicationEnvironmentApi.rebind).not.toHaveBeenCalled();
});
it('ignores late responses after owner navigation and exposes only explicit new-environment choice for incompatible packages', async () => {
  let finish!: (value: Preview) => void;
  vi.mocked(applicationEnvironmentApi.continuation).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  await mount(); await click('核对恢复条件'); await mount('different-owner'); await act(async () => finish(preview));
  expect(host.textContent).not.toContain('确认新凭据绑定'); expect(applicationEnvironmentApi.rebind).not.toHaveBeenCalled();
  vi.mocked(applicationEnvironmentApi.continuation).mockResolvedValue({ ...preview, canRebind: false, classification: 'needs-new-run', nextAction: 'new-environment' });
  await mount(); await click('核对恢复条件'); expect(newEnvironment).not.toHaveBeenCalled();
  await click('创建新环境，保留旧结果'); expect(newEnvironment).toHaveBeenCalledTimes(1); expect(applicationEnvironmentApi.prepare).not.toHaveBeenCalled();
});
