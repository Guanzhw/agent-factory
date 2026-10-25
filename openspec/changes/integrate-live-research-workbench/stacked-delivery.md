# Standalone stacked UI delivery

- Original construction base: `5ffb7c343631c1a0839dab0030355c86eb8a8b75` (backend PR121).
- Current review base: `35a9783723a204efda26e8a3f46b105dc4cf61ae` (backend PR121 refreshed with merged main PR122/PR123).
- Source/evidence tip before this metadata-only note: `3fcea43d8634e5532e593ce2fd43e4573e46dbcc`.
- Local branch: `impl/research-workbench-stacked-20261025`.
- No product conflict occurred. No new feature or browser rerun was introduced.

Original UI commits `085ebab`, `157e0e7`, `2495ac4`, `271b392`, `09a2eae`, `14b2bc0` were cherry-picked in order, preserving spec-before-implementation and both regression repairs. Evidence commits `1cc8697`, `a607487`, `1e001c4`, `1b58d79` were then cherry-picked in order, preserving first failures, diagnostic conclusions, whitespace-only log normalization and the final actual browser result. Core tool metadata/QA commits were not cherry-picked as UI changes. The refreshed backend base now inherits the separately merged core PR122/PR123 changes; those are excluded from the UI review diff.

`git diff --exit-code 341c35700a5ac799f0ed9617c646ad70014d7ad5 3fcea43d8634e5532e593ce2fd43e4573e46dbcc -- web shared tests/research-demo-navigation.test.ts scripts/accept_live_research_workbench.py openspec/changes/integrate-live-research-workbench` exited **0**. Thus the entire frontend (including unchanged core/demo files), relevant navigation tests, browser fixture and existing evidence are byte-identical to the integrated product snapshot. Base-to-head `git diff --check` also exited **0**. The new note is the only extra evidence metadata.

The browser evidence remains bound to integrated product `9ce15e4`, as recorded in verification; it is not a claim that backend PR121 alone contains every required core repair. The native-tool metadata repair `4956857` / core PR123 is now present through the refreshed backend base, resolving that source dependency. This merge changed no frontend or browser fixture bytes and required no conflict resolution. No browser run was repeated on the refreshed head: do not re-label the integrated browser result as an execution of this standalone stacked head. Root owns final dependency ordering, exact-head CI and independent review. No symlink, node_modules, secret, core-auth source or QA implementation was added.

## Exact original-base-to-UI/evidence-tip file list

```text
A	openspec/changes/integrate-live-research-workbench/.openspec.yaml
A	openspec/changes/integrate-live-research-workbench/design.md
A	openspec/changes/integrate-live-research-workbench/evidence/browser-projects.py
A	openspec/changes/integrate-live-research-workbench/evidence/first-fixture-failure.txt
A	openspec/changes/integrate-live-research-workbench/evidence/full-web-first-failure.txt
A	openspec/changes/integrate-live-research-workbench/evidence/live-browser-terminal.json
A	openspec/changes/integrate-live-research-workbench/evidence/live-evidence-desktop.png
A	openspec/changes/integrate-live-research-workbench/evidence/live-evidence-mobile.png
A	openspec/changes/integrate-live-research-workbench/evidence/live-platform-desktop.png
A	openspec/changes/integrate-live-research-workbench/evidence/live-platform-mobile.png
A	openspec/changes/integrate-live-research-workbench/evidence/null-observation-first-failure.txt
A	openspec/changes/integrate-live-research-workbench/evidence/owner-wait-tool-first-failure.txt
A	openspec/changes/integrate-live-research-workbench/evidence/project-browser.json
A	openspec/changes/integrate-live-research-workbench/evidence/project-desktop.png
A	openspec/changes/integrate-live-research-workbench/evidence/project-mobile.png
A	openspec/changes/integrate-live-research-workbench/evidence/publication-targeted.txt
A	openspec/changes/integrate-live-research-workbench/evidence/real-browser-owner-model-first-failure.md
A	openspec/changes/integrate-live-research-workbench/evidence/start-refresh-first-failure.txt
A	openspec/changes/integrate-live-research-workbench/independent-review.md
A	openspec/changes/integrate-live-research-workbench/proposal.md
A	openspec/changes/integrate-live-research-workbench/specs/research-workbench/spec.md
A	openspec/changes/integrate-live-research-workbench/tasks.md
A	openspec/changes/integrate-live-research-workbench/verification.md
A	scripts/accept_live_research_workbench.py
M	tests/research-demo-navigation.test.ts
M	web/apps/research/ResearchWorkspace.test.ts
M	web/apps/research/ResearchWorkspace.tsx
M	web/apps/research/client.ts
A	web/apps/research/live/Dialog.tsx
A	web/apps/research/live/ExecutionEditor.test.ts
A	web/apps/research/live/ExecutionEditor.tsx
A	web/apps/research/live/ProjectDetails.tsx
A	web/apps/research/live/ResearchWorkbench.test.ts
A	web/apps/research/live/ResearchWorkbench.tsx
A	web/apps/research/live/RunRecords.test.ts
A	web/apps/research/live/RunRecords.tsx
A	web/apps/research/live/SetupPanel.test.ts
A	web/apps/research/live/SetupPanel.tsx
A	web/apps/research/live/runs.ts
A	web/apps/research/live/setupClient.ts
A	web/apps/research/live/workbench.css
D	web/apps/research/research.css
M	web/apps/research/types.ts
A	web/apps/research/useProjectCommand.tsx
M	web/research-composition.tsx
```

This `stacked-delivery.md` is additionally created by the final metadata commit.
