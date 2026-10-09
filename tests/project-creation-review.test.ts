import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it } from 'vitest';
import { ProjectCreationReview, projectCreationSummary, needsProjectCreationSummary } from '../web/ProjectCreationReview.js';
import type { PersonalOrxProjectReviewSummary, PlanReview } from '../web/models.js';

const summary: PersonalOrxProjectReviewSummary = {
  schema: 'native-orx-project-review-v1', requestId: 'synthetic-request', previewHash: 'a'.repeat(64),
  project: { name: '<script>Synthetic project</script>', path: '/synthetic/immutable', source: 'clone', cloneUrl: 'https://github.com/synthetic-fixture/example', paperId: null },
  effects: { version: 'native-orx-create-consent-v2', remotePath: '/synthetic/immutable', repository: 'https://github.com/synthetic-fixture/example', paperId: null, remoteWrites: 'clone-into-new-or-existing-empty-folder-and-project', clone: true, paperDownload: false, gitInitialization: false, githubSyncEnabled: false, pathResolution: 'upstream-clone-target-symlinks-followed-no-new-folder-guarantee', starterSuggestions: 'may-request-four-project-chat-suggestions', modelInput: ['README', 'selected-code', 'file-list', 'paper-summary'], modelSelection: 'remote-preferred-or-ready-harness', billing: 'owner-remote-account-possible-cost', hardBudgetEnforced: false, automaticExperiment: false, emptyCacheHitOrNoHarness: 'may-skip-model-request', unknownResponse: 'read-only-reconcile-never-resend' },
  billing: { controllerLedgerScope: 'local-controller-only', remoteUsageStatus: 'unknown', remoteCostStatus: 'unknown', remoteBilling: 'owner-remote-account-possible-cost', remoteCostIncludedInUsageBudget: false, hardRemoteBudgetEnforced: false }, ownerConsentSeparate: true,
};
const review = (projectCreation?: PersonalOrxProjectReviewSummary) => ({ planSummary: { application: 'personal-orx-project-create-v1', projectCreation } }) as PlanReview;
it('requires the server immutable creation summary even when generic plan metadata is present', () => {
  expect(needsProjectCreationSummary(review())).toBe(true);
  expect(projectCreationSummary(review())).toBeUndefined();
  expect(projectCreationSummary(review(summary))).toBe(summary);
});
it('rejects contradictory path, clone scope and remote cost promises', () => {
  for (const changed of [
    { ...summary, effects: { ...summary.effects, remotePath: '/different' } },
    { ...summary, effects: { ...summary.effects, clone: false } },
    { ...summary, billing: { ...summary.billing, remoteCostStatus: 'free' } },
    { ...summary, billing: { ...summary.billing, hardRemoteBudgetEnforced: true } },
  ]) expect(projectCreationSummary(review(changed as PersonalOrxProjectReviewSummary))).toBeUndefined();
});
it('shows exact escaped side effects and owner confirmation while financial details remain folded', () => {
  const html = renderToStaticMarkup(createElement(ProjectCreationReview, { value: summary }));
  expect(html).toContain('&lt;script&gt;Synthetic project&lt;/script&gt;'); expect(html).not.toContain('<script>');
  expect(html).toContain('/synthetic/immutable'); expect(html).toContain(summary.project.cloneUrl!);
  expect(html).toContain('新目录或已有空目录'); expect(html).toContain('符号链接');
  expect(html).toContain('拥有者确认后才会提交远端副作用'); expect(html).not.toContain('管理员同意后'); expect(html).not.toContain('<strong>远端用量与费用未知</strong>');
  expect(html).not.toContain('<details open');
});
