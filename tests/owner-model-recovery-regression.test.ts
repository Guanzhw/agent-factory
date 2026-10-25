// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../web/api.js';
import { ModelSettings } from '../web/ModelSettings.js';
import { ModelRequestError, ownerModelApi, type OwnerModel } from '../web/ownerModelApi.js';
import { personalRemoteApi, RemoteRequestError } from '../web/personalRemoteApi.js';
import type { ModelSetup } from '../web/ownerModelSetup.js';

// Only public synthetic references are used. Every API is mocked and fetch is denied.
const owner = 'recovery-fixture-owner';
const storage = `factory-model-setup:${owner}`;
const unresolvedStorage = `${storage}:unresolved`;
const credential = {
  credentialRef: 'recovery-fixture-credential', credentialRevision: 'credential-r1',
  providerId: 'byok-chat-v1', destination: 'https://models.example', status: 'active',
};
const model: OwnerModel = {
  reference: 'recovery-fixture-model', revision: 'model-r1', connectionRef: 'connection-r1', ownerId: owner, visibility: 'personal', isOwner: true,
  provider: 'openai-compatible', baseURL: 'https://models.example/v1', model: 'fixture-model',
  credentialRef: credential.credentialRef, credentialRevision: credential.credentialRevision,
  updatedAt: '2026-10-13T00:00:00Z', status: 'configured', available: true, isDefault: false,
};
let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('crypto', webcrypto);
  vi.stubGlobal('fetch', vi.fn(() => { throw new Error('Network forbidden in recovery regression'); }));
  localStorage.clear();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  vi.spyOn(api, 'session').mockResolvedValue({ id: owner, name: 'Synthetic fixture', role: 'user' });
  vi.spyOn(ownerModelApi, 'capabilities').mockResolvedValue({ enabled: true, providers: ['openai', 'openai-compatible'], liveCompatibilityVerified: false });
  vi.spyOn(ownerModelApi, 'list').mockResolvedValue([]);
  vi.spyOn(ownerModelApi, 'configure').mockResolvedValue(model);
  vi.spyOn(ownerModelApi, 'default').mockResolvedValue({ ...model, isDefault: true });
  vi.spyOn(ownerModelApi, 'revoke').mockRejectedValue(new Error('Unexpected model revoke'));
  vi.spyOn(ownerModelApi, 'recover').mockRejectedValue(new ModelRequestError(0));
  vi.spyOn(personalRemoteApi, 'credentials').mockResolvedValue([credential]);
  vi.spyOn(personalRemoteApi, 'recoverCredential').mockResolvedValue(credential);
  vi.spyOn(personalRemoteApi, 'saveCredential').mockRejectedValue(new Error('Secret writes forbidden'));
  vi.spyOn(personalRemoteApi, 'rotateCredential').mockRejectedValue(new Error('Secret writes forbidden'));
});

afterEach(async () => {
  try {
    await act(async () => root.unmount());
    expect(fetch).not.toHaveBeenCalled();
    expect(personalRemoteApi.saveCredential).not.toHaveBeenCalled();
    expect(personalRemoteApi.rotateCredential).not.toHaveBeenCalled();
    expect(ownerModelApi.revoke).not.toHaveBeenCalled();
    expect(JSON.stringify(localStorage)).not.toMatch(/"(?:password|apiKey|secret)"\s*:/);
  } finally {
    host.remove(); localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals();
  }
});

async function mount() {
  await act(async () => root.render(createElement(ModelSettings, { ownerId: owner, onBack: vi.fn() })));
}
async function remount() {
  await act(async () => root.unmount()); root = createRoot(host); await mount();
}
async function click(label: string) {
  const button = [...host.querySelectorAll('button')].find(element => element.textContent === label);
  expect(button, `button ${label}`).toBeDefined();
  await act(async () => button!.click());
}
async function select(label: string, value: string) {
  await act(async () => {
    const element = host.querySelector<HTMLSelectElement>(`[aria-label="${label}"]`)!;
    element.value = value; element.dispatchEvent(new Event('change', { bubbles: true }));
  });
}
async function fill(label: string, value: string) {
  await act(async () => {
    const element = host.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(element, value);
    element.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
async function saveWithExistingCredential() {
  await select('模型提供方', 'openai-compatible');
  await fill('API 端点', model.baseURL); await fill('模型名称', model.model);
  await select('模型凭据来源', 'saved');
  await select('已保存的模型凭据', credential.credentialRef);
  expect(host.querySelector('[aria-label="API 密钥"]')).toBeNull();
  await click('保存模型并设为默认');
}
function formAvailable() {
  const input = host.querySelector<HTMLInputElement>('[aria-label="模型名称"]');
  return input !== null && !input.disabled && !input.closest('fieldset')!.disabled;
}

it.each([403, 422])('releases a definitively rejected configure (%s) after reread and remount without another write', async status => {
  vi.mocked(ownerModelApi.configure).mockRejectedValue(new ModelRequestError(status));
  await mount(); await saveWithExistingCredential();
  const originalCall = vi.mocked(ownerModelApi.configure).mock.calls[0];
  const observations = [{ phase: 'after rejection', formAvailable: formAvailable() }];
  await click('重新读取设置');
  observations.push({ phase: 'after reread', formAvailable: formAvailable() });
  await remount();
  observations.push({ phase: 'after remount', formAvailable: formAvailable() });
  expect(ownerModelApi.configure).toHaveBeenCalledTimes(1);
  expect(ownerModelApi.configure).toHaveBeenLastCalledWith(...originalCall);
  expect(ownerModelApi.default).not.toHaveBeenCalled();
  expect(personalRemoteApi.recoverCredential).not.toHaveBeenCalled();
  // The assertion is about recovery of the existing form, not a new API or button.
  expect(observations).toEqual([
    { phase: 'after rejection', formAvailable: true },
    { phase: 'after reread', formAvailable: true },
    { phase: 'after remount', formAvailable: true },
  ]);
});

it('settles an acknowledged original default after another tab changes the current default without issuing a new intent', async () => {
  let currentDefault: string | undefined;
  const committedRequests = new Set<string>();
  vi.mocked(ownerModelApi.default).mockImplementation(async (_owner, reference, requestId) => {
    committedRequests.add(requestId); currentDefault = reference;
    throw new ModelRequestError(0); // The command committed, but its response was lost.
  });
  await mount(); await saveWithExistingCredential();
  const originalRequest = vi.mocked(ownerModelApi.default).mock.calls[0][2];
  expect(currentDefault).toBe(model.reference);
  expect(host.textContent).toContain('上次保存尚未确认');
  currentDefault = 'other-tab-fixture-model';
  vi.mocked(ownerModelApi.list).mockResolvedValue([
    model, { ...model, reference: currentDefault, model: 'other-fixture-model', isDefault: true },
  ]);
  const completedAt = '2026-10-13T00:01:00Z';
  vi.mocked(ownerModelApi.recover).mockResolvedValue({ ownerId: owner, requestId: originalRequest, action: 'model.default', result: { ...model, isDefault: true }, completedAt });
  await remount(); await click('核对并继续原保存'); await click('重新读取设置');
  expect(ownerModelApi.configure).toHaveBeenCalledTimes(1);
  expect(ownerModelApi.default).toHaveBeenCalledTimes(1);
  expect(ownerModelApi.recover).toHaveBeenCalledWith(owner, originalRequest);
  expect([...committedRequests]).toEqual([originalRequest]);
  expect(host.textContent).toContain('other-fixture-model');
  expect(currentDefault).toBe('other-tab-fixture-model');
  expect(personalRemoteApi.recoverCredential).not.toHaveBeenCalled();
  expect(host.textContent).not.toContain('模型已保存并设为默认');
  expect(host.textContent).toContain('other-fixture-model');
  // A changed current selection must not trap every future model operation.
  expect(formAvailable()).toBe(true);
});

it.each([403, 404])('keeps UNKNOWN configure pending when receipt lookup returns %s, without a second POST', async status => {
  vi.mocked(ownerModelApi.configure).mockRejectedValue(new ModelRequestError(0));
  vi.mocked(ownerModelApi.recover).mockRejectedValue(new ModelRequestError(status));
  await mount(); await saveWithExistingCredential();
  const requestId = vi.mocked(ownerModelApi.configure).mock.calls[0][1].requestId;
  const originalPending = localStorage.getItem(storage);
  expect(originalPending).not.toBeNull();
  expect(JSON.parse(originalPending!).dispatched).toEqual({ model: true });
  await remount(); await click('核对并继续原保存');
  expect(ownerModelApi.configure).toHaveBeenCalledTimes(1);
  expect(ownerModelApi.recover).toHaveBeenCalledWith(owner, requestId);
  expect(localStorage.getItem(storage)).toBe(originalPending);
  expect(host.textContent).toContain('上次保存尚未确认');
  expect(ownerModelApi.default).not.toHaveBeenCalled();
  expect(personalRemoteApi.recoverCredential).not.toHaveBeenCalled();
});

it('archives waiting and checks a completed configure receipt with GET only', async () => {
  vi.mocked(ownerModelApi.configure).mockRejectedValue(new ModelRequestError(0));
  await mount(); await saveWithExistingCredential();
  const requestId = vi.mocked(ownerModelApi.configure).mock.calls[0][1].requestId;
  vi.mocked(ownerModelApi.recover).mockResolvedValue({ ownerId: owner, requestId, action: 'model.configure', result: model, completedAt: '2026-10-13T00:01:00Z' });
  await click('停止等待此保存');
  await click('确认停止等待并保留原请求');
  expect(localStorage.getItem(storage)).toBeNull();
  expect(formAvailable()).toBe(true);
  expect(JSON.parse(localStorage.getItem(unresolvedStorage)!)).toHaveLength(1);
  await click('核对保留的原请求');
  expect(ownerModelApi.recover).toHaveBeenCalledWith(owner, requestId);
  expect(ownerModelApi.configure).toHaveBeenCalledTimes(1);
  expect(ownerModelApi.default).not.toHaveBeenCalled();
  expect(localStorage.getItem(storage)).toBeNull();
  expect(JSON.parse(localStorage.getItem(unresolvedStorage)!)).toHaveLength(0);
});

it('only reads an UNKNOWN historical credential request after remount and never replays a secret', async () => {
  const pending: ModelSetup = {
    owner, provider: model.provider, baseURL: model.baseURL, model: model.model,
    credentialRequest: 'fixture-unknown-credential-request', modelRequest: 'fixture-not-sent-model-request',
    defaultRequest: 'fixture-not-sent-default-request', stage: 'credential', chooseDefault: true,
    reference: model.reference,
    rotating: { credentialRef: credential.credentialRef, credentialRevision: credential.credentialRevision },
  };
  localStorage.setItem(storage, JSON.stringify(pending));
  vi.mocked(personalRemoteApi.recoverCredential).mockRejectedValue(new RemoteRequestError(false));
  await mount(); await click('核对并继续原保存'); await remount(); await click('核对并继续原保存');
  expect(vi.mocked(personalRemoteApi.recoverCredential).mock.calls).toEqual([
    [pending.credentialRequest, owner], [pending.credentialRequest, owner],
  ]);
  expect(JSON.parse(localStorage.getItem(storage)!)).toEqual(pending);
  expect(host.textContent).toContain('上次保存尚未确认');
  expect(ownerModelApi.configure).not.toHaveBeenCalled();
  expect(ownerModelApi.default).not.toHaveBeenCalled();
  expect(ownerModelApi.recover).not.toHaveBeenCalled();
});

it('allows the first model POST for a current stage with an explicit empty dispatched marker', async () => {
  const pending: ModelSetup = {
    owner, provider: model.provider, baseURL: model.baseURL, model: model.model,
    credentialRequest: 'fixture-credential-request', modelRequest: 'fixture-model-request',
    defaultRequest: 'fixture-default-request', stage: 'model', chooseDefault: true, dispatched: {}, credential,
  };
  localStorage.setItem(storage, JSON.stringify(pending));
  await mount(); await click('核对并继续原保存');
  expect(ownerModelApi.recover).not.toHaveBeenCalled();
  expect(ownerModelApi.configure).toHaveBeenCalledTimes(1);
  expect(ownerModelApi.configure).toHaveBeenCalledWith(owner, expect.objectContaining({ requestId: pending.modelRequest }), undefined);
  expect(ownerModelApi.default).toHaveBeenCalledTimes(1);
  expect(ownerModelApi.default).toHaveBeenCalledWith(owner, model.reference, pending.defaultRequest);
});

it('recovers a dispatched model once, then sends only its original unstarted default request', async () => {
  const pending: ModelSetup = {
    owner, provider: model.provider, baseURL: model.baseURL, model: model.model,
    credentialRequest: 'fixture-credential-request', modelRequest: 'fixture-model-request',
    defaultRequest: 'fixture-default-request', stage: 'model', chooseDefault: true,
    dispatched: { model: true }, credential,
  };
  localStorage.setItem(storage, JSON.stringify(pending));
  vi.mocked(ownerModelApi.recover).mockResolvedValue({ ownerId: owner, requestId: pending.modelRequest, action: 'model.configure', result: model, completedAt: '2026-10-13T00:01:00Z' });
  await mount(); await click('核对并继续原保存');
  expect(ownerModelApi.recover).toHaveBeenCalledWith(owner, pending.modelRequest);
  expect(ownerModelApi.configure).not.toHaveBeenCalled();
  expect(ownerModelApi.default).toHaveBeenCalledTimes(1);
  expect(ownerModelApi.default).toHaveBeenCalledWith(owner, model.reference, pending.defaultRequest);
});

it.each(['model', 'default'] as const)('releases a first %s POST rejected after the prior stage is recovered', async stage => {
  const pending: ModelSetup = {
    owner, provider: model.provider, baseURL: model.baseURL, model: model.model,
    credentialRequest: 'fixture-credential-request', modelRequest: 'fixture-model-request',
    defaultRequest: 'fixture-default-request', stage: stage === 'model' ? 'credential' : 'model', chooseDefault: true,
    ...(stage === 'default' ? { dispatched: { model: true as const }, credential } : { dispatched: {} }),
  };
  localStorage.setItem(storage, JSON.stringify(pending));
  if (stage === 'model') vi.mocked(ownerModelApi.configure).mockRejectedValue(new ModelRequestError(422));
  else {
    vi.mocked(ownerModelApi.recover).mockResolvedValue({ ownerId: owner, requestId: pending.modelRequest, action: 'model.configure', result: model, completedAt: '2026-10-13T00:01:00Z' });
    vi.mocked(ownerModelApi.default).mockRejectedValue(new ModelRequestError(422));
  }
  await mount(); await click('核对并继续原保存');
  expect(localStorage.getItem(storage)).toBeNull();
  expect(formAvailable()).toBe(true);
  if (stage === 'model') {
    expect(personalRemoteApi.recoverCredential).toHaveBeenCalledWith(pending.credentialRequest, owner);
    expect(ownerModelApi.configure).toHaveBeenCalledTimes(1);
    expect(ownerModelApi.default).not.toHaveBeenCalled();
  } else {
    expect(ownerModelApi.recover).toHaveBeenCalledWith(owner, pending.modelRequest);
    expect(ownerModelApi.default).toHaveBeenCalledTimes(1);
    expect(ownerModelApi.configure).not.toHaveBeenCalled();
  }
});

it('conservatively reads legacy model-stage metadata and does not replay its configure request', async () => {
  const pending: ModelSetup = {
    owner, provider: model.provider, baseURL: model.baseURL, model: model.model,
    credentialRequest: 'fixture-credential-request', modelRequest: 'fixture-model-request',
    defaultRequest: 'fixture-default-request', stage: 'model', chooseDefault: false, credential,
  };
  localStorage.setItem(storage, JSON.stringify(pending));
  vi.mocked(ownerModelApi.recover).mockResolvedValue({ ownerId: owner, requestId: pending.modelRequest, action: 'model.configure', result: model, completedAt: '2026-10-13T00:01:00Z' });
  await mount(); await click('核对并继续原保存');
  expect(ownerModelApi.recover).toHaveBeenCalledWith(owner, pending.modelRequest);
  expect(ownerModelApi.configure).not.toHaveBeenCalled();
  expect(ownerModelApi.default).not.toHaveBeenCalled();
});

it('does not overwrite another tab\'s retained request from a stale unlocked form', async () => {
  await mount();
  const otherTab: ModelSetup = {
    owner, provider: model.provider, baseURL: model.baseURL, model: model.model,
    credentialRequest: 'other-tab-credential-request', modelRequest: 'other-tab-model-request',
    defaultRequest: 'other-tab-default-request', stage: 'model', chooseDefault: false,
    dispatched: { model: true }, credential,
  };
  localStorage.setItem(storage, JSON.stringify(otherTab));
  await saveWithExistingCredential();
  expect(JSON.parse(localStorage.getItem(storage)!)).toEqual(otherTab);
  expect(ownerModelApi.configure).not.toHaveBeenCalled();
  expect(ownerModelApi.default).not.toHaveBeenCalled();
  expect(host.textContent).toContain('上次保存尚未确认');
});

it('does not send the next stage after another tab archives the still-running request', async () => {
  let complete!: (value: OwnerModel) => void;
  vi.mocked(ownerModelApi.configure).mockImplementation(() => new Promise(resolve => { complete = resolve; }));
  await mount(); await saveWithExistingCredential();
  const original = JSON.parse(localStorage.getItem(storage)!);
  localStorage.setItem(unresolvedStorage, JSON.stringify([original])); localStorage.removeItem(storage);
  await act(async () => complete(model));
  expect(ownerModelApi.configure).toHaveBeenCalledTimes(1);
  expect(ownerModelApi.default).not.toHaveBeenCalled();
  expect(localStorage.getItem(storage)).toBeNull();
  expect(JSON.parse(localStorage.getItem(unresolvedStorage)!)).toEqual([original]);
});

it('does not resume a delayed configure after another tab settles its archive and chooses a new default', async () => {
  let completeConfigure!: (value: OwnerModel) => void;
  const other = { ...model, reference: 'second-tab-model', model: 'second-tab-model' };
  let currentDefault: string | undefined;
  vi.mocked(ownerModelApi.configure).mockImplementation(() => new Promise(resolve => { completeConfigure = resolve; }));
  vi.mocked(ownerModelApi.list).mockImplementation(async () => [other, model].map(record => ({ ...record, isDefault: currentDefault === record.reference })));
  vi.mocked(ownerModelApi.default).mockImplementation(async (_owner, reference) => {
    currentDefault = reference;
    return { ...(reference === other.reference ? other : model), isDefault: true };
  });
  await mount(); await saveWithExistingCredential();
  const firstRequest = JSON.parse(localStorage.getItem(storage)!) as ModelSetup;
  vi.mocked(ownerModelApi.recover).mockResolvedValue({ ownerId: owner, requestId: firstRequest.modelRequest,
    action: 'model.configure', result: model, completedAt: '2026-10-13T00:01:00Z' });

  // Two live ModelSettings roots share browser storage; the first POST is still
  // awaiting its response while the second root uses the actual recovery UI.
  const firstHost = host; const firstRoot = root;
  const secondHost = document.createElement('div'); document.body.append(secondHost);
  const secondRoot = createRoot(secondHost);
  host = secondHost; root = secondRoot;
  try {
    await mount(); await click('停止等待此保存'); await click('确认停止等待并保留原请求');
    expect(JSON.parse(localStorage.getItem(unresolvedStorage)!)).toHaveLength(1);
    await click('核对保留的原请求');
    expect(ownerModelApi.recover).toHaveBeenCalledWith(owner, firstRequest.modelRequest);
    expect(JSON.parse(localStorage.getItem(unresolvedStorage)!)).toEqual([]);
    expect(localStorage.getItem(storage)).toBeNull();
    await click('设为默认');
    expect(currentDefault).toBe(other.reference);
    expect(ownerModelApi.default).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(storage)).toBeNull();

    await act(async () => completeConfigure(model));
    expect(ownerModelApi.configure).toHaveBeenCalledTimes(1);
    expect(ownerModelApi.default).toHaveBeenCalledTimes(1);
    expect(ownerModelApi.default).not.toHaveBeenCalledWith(owner, model.reference, firstRequest.defaultRequest);
    expect(currentDefault).toBe(other.reference);
    expect(localStorage.getItem(storage)).toBeNull();
    expect(JSON.parse(localStorage.getItem(unresolvedStorage)!)).toEqual([]);
    expect(firstHost.textContent).not.toContain('模型已保存并设为默认');
  } finally {
    await act(async () => secondRoot.unmount()); secondHost.remove(); host = firstHost; root = firstRoot;
  }
});

it('ignores a delayed default completion after another tab settles it and selects another default', async () => {
  let completeDefault!: (value: OwnerModel) => void;
  const other = { ...model, reference: 'new-default-model', model: 'new-default-model' };
  let currentDefault: string | undefined;
  vi.mocked(ownerModelApi.list).mockImplementation(async () => [model, other].map(record => ({ ...record, isDefault: currentDefault === record.reference })));
  vi.mocked(ownerModelApi.default).mockImplementation(async (_owner, reference) => {
    currentDefault = reference;
    if (reference === model.reference) return new Promise(resolve => { completeDefault = resolve; });
    return { ...other, isDefault: true };
  });
  await mount(); await click('设为默认');
  const original = JSON.parse(localStorage.getItem(storage)!) as ModelSetup;
  vi.mocked(ownerModelApi.recover).mockResolvedValue({ ownerId: owner, requestId: original.defaultRequest,
    action: 'model.default', result: { ...model, isDefault: true }, completedAt: '2026-10-13T00:01:00Z' });

  const firstHost = host; const firstRoot = root;
  const secondHost = document.createElement('div'); document.body.append(secondHost);
  const secondRoot = createRoot(secondHost);
  host = secondHost; root = secondRoot;
  try {
    await mount(); await click('停止等待此保存'); await click('确认停止等待并保留原请求');
    await click('核对保留的原请求');
    expect(ownerModelApi.recover).toHaveBeenCalledWith(owner, original.defaultRequest);
    expect(JSON.parse(localStorage.getItem(unresolvedStorage)!)).toEqual([]);
    await click('设为默认');
    expect(currentDefault).toBe(other.reference);
    await act(async () => completeDefault({ ...model, isDefault: true }));
    expect(ownerModelApi.configure).not.toHaveBeenCalled();
    expect(ownerModelApi.default).toHaveBeenCalledTimes(2);
    expect(vi.mocked(ownerModelApi.default).mock.calls.map(call => call[1])).toEqual([model.reference, other.reference]);
    expect(currentDefault).toBe(other.reference);
    expect(localStorage.getItem(storage)).toBeNull();
    expect(firstHost.textContent).not.toContain('默认模型已更新');
    expect(firstHost.textContent).not.toContain('模型已保存并设为默认');
  } finally {
    await act(async () => secondRoot.unmount()); secondHost.remove(); host = firstHost; root = firstRoot;
  }
});

it('finishes a valid saved-credential configuration and default without leaving pending state', async () => {
  await mount(); await saveWithExistingCredential();
  expect(ownerModelApi.configure).toHaveBeenCalledTimes(1);
  expect(ownerModelApi.default).toHaveBeenCalledTimes(1);
  expect(ownerModelApi.configure).toHaveBeenCalledWith(owner, expect.objectContaining({
    credentialRef: credential.credentialRef, credentialRevision: credential.credentialRevision,
  }), undefined);
  expect(personalRemoteApi.recoverCredential).not.toHaveBeenCalled();
  expect(localStorage.getItem(storage)).toBeNull();
  expect(host.textContent).toContain('模型已保存并设为默认');
  expect(formAvailable()).toBe(true);
});
