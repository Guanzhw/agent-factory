// @vitest-environment happy-dom
import { act, createElement, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { EvidenceSelection } from './EvidenceSelection.js';
import { setupApi } from './setupClient.js';
import type { ResearchAgreement } from '../types.js';

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it('defaults old choices to CLI and clears incompatible material and fields on an explicit SSH switch', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const pin = { id: 'original-cli', version: 1, sha256: 'a'.repeat(64) };
  const ssh = { id: 'ssh-launch', version: 2, sha256: 'b'.repeat(64) };
  const change = vi.fn();
  vi.spyOn(setupApi, 'candidates').mockResolvedValue({ workflowPin: { kind: 'workflow', id: 'research', revision: '1', sha256: 'c'.repeat(64) }, models: [], connections: [], environments: [], experimentMaterials: [{ ...ssh, name: 'SSH launch', available: true, connectionRequirements: [] }] });
  function Form() {
    const [value, setValue] = useState<NonNullable<ResearchAgreement['evidence']> | null>({ toolMaterial: pin, fields: { metrics: 'measurement' } });
    return createElement(EvidenceSelection, { ownerId: 'alice', value, onChange: next => { change(next); setValue(next); }, onMaterials: vi.fn() });
  }
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  try {
    await act(async () => root.render(createElement(Form)));
    expect(host.querySelector('select')!.value).toBe('cli');
    expect(change).not.toHaveBeenCalled();
    await act(async () => { const source = host.querySelector('select')!; source.value = 'ssh-process'; source.dispatchEvent(new Event('change', { bubbles: true })); });
    expect(change).toHaveBeenLastCalledWith(null);
    expect(host.textContent).not.toContain('original-cli');
    await act(async () => [...host.querySelectorAll('button')].find(button => button.textContent === '读取已发布实验材料')!.click());
    await act(async () => { const material = host.querySelectorAll('select')[1]; material.value = `${ssh.id}:${ssh.version}:${ssh.sha256}`; material.dispatchEvent(new Event('change', { bubbles: true })); });
    expect(change).toHaveBeenLastCalledWith({ kind: 'ssh-process', toolMaterial: ssh, fields: {} });
    expect(host.textContent).toContain('完整stdout须是单个JSON对象');
  } finally { await act(async () => root.unmount()); host.remove(); }
});
