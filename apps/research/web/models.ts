export interface PersonalOrxProjectReviewSummary {
  schema: 'native-orx-project-review-v1'; requestId: string; previewHash: string;
  project: { name: string; path: string; source: 'empty' | 'existing' | 'clone' | 'paper'; cloneUrl: string | null; paperId: string | null };
  effects: { version: 'native-orx-create-consent-v2'; remotePath: string; repository: string | null; paperId: string | null; remoteWrites: string; clone: boolean; paperDownload: boolean; gitInitialization: boolean; githubSyncEnabled: false; pathResolution: string; starterSuggestions: string; modelInput: string[]; modelSelection: string; billing: 'owner-remote-account-possible-cost'; hardBudgetEnforced: false; automaticExperiment: false; emptyCacheHitOrNoHarness: string; unknownResponse: 'read-only-reconcile-never-resend' };
  billing: { controllerLedgerScope: 'local-controller-only'; remoteUsageStatus: 'unknown'; remoteCostStatus: 'unknown'; remoteBilling: 'owner-remote-account-possible-cost'; remoteCostIncludedInUsageBudget: false; hardRemoteBudgetEnforced: false };
  ownerConsentSeparate: true;
}

