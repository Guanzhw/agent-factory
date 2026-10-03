import { createElement } from 'react';
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ApprovedRecoveryPanel, approvedRecovery } from '../web/ApprovedRecovery.js';
import type { FactoryJob } from '../web/models.js';

const recovery = { approvalCommandId: 'original-approved-command', requirementId: 'native-requirement', version: 12,
  runId: 'original-native-run', scope: '复用原实验结果并继续当前任务' };
const job = { status: 'waiting_approval', allowedActions: ['resume_approved'], recoveryDetail: recovery } as FactoryJob;
describe('recorded approval recovery', () => {
  it('requires a current explicit recovery action and complete original references', () => {
    expect(approvedRecovery(job)).toEqual(recovery);
    expect(approvedRecovery({ ...job, allowedActions: ['approve'] })).toBeNull();
    expect(approvedRecovery({ ...job, status: 'running' })).toBeNull();
    expect(approvedRecovery({ ...job, recoveryDetail: { ...recovery, approvalCommandId: '' } })).toBeNull();
    expect(approvedRecovery({ ...job, recoveryDetail: { ...recovery, version: NaN } })).toBeNull();
  });
  it('describes reuse and later budgeted inference without submitting on render', () => {
    let calls = 0;
    const html = renderToStaticMarkup(createElement(ApprovedRecoveryPanel, { recovery, busy: true, submit: () => calls++ }));
    expect(html).toContain('恢复本次执行');expect(html).toContain('当前权限和预算');expect(html).toContain('disabled');
    expect(calls).toBe(0);
  });
});
