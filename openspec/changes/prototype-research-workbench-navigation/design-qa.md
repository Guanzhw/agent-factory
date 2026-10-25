# Independent design and implementation review

## Scope and result

**PASS for the isolated synthetic UI demo at the reviewed code revision.** No remaining P0/P1/P2 findings in this review. This is not approval to merge the formal research UI, nor evidence of real research execution, team sharing, external identity integration or GPU use.

- Reviewer: independent `pr104_independent_review` agent; not the UI author.
- Complete review base: `f25c8992f5c286db3cca3554e3c74a255dfe9f82`.
- Reviewed head: `2fbc24ca7bb4cc7703a4a2f5c7884f326f0442b2`.
- Includes the prototype specification, generic login-return integration, demo composition/components/styles/data, navigation and session tests, browser script, dependencies, architecture/Vite wiring, and the two connection component key corrections.
- Review method: complete diff/source reading, direct image inspection and inspection of recorded browser evidence. No heavy tests were rerun by the reviewer. Subsequent source changes require review of the affected diff and evidence.

## Actual visual comparison

The selected reference `/workspace/agent-factory-design-reference/research-workbench.png` and **iteration 4** render `/tmp/af-research-demo-evidence/interaction-4/workbench-1487.png` were loaded together into the same visual comparison input, both at 1487 × 1058. The initial workbench state matches. The same comparison also included `workbench-390.png` at 390 × 844. Full-screen composition and the table, chart and assistant text were inspected; iteration 1 screenshots were not reused as proof of the revised rendering.

| Surface | Observed result |
| --- | --- |
| Typography | Revised project-next text, assistant body, reference labels and chart labels restore the intended hierarchy. Chinese wrapping is close, not pixel-identical. The main title, section title and supporting copy remain distinct. |
| Spacing | The three columns, table and project card align closely with the reference. The primary button now has the reference width. Chart inset and vertical rhythm have been corrected; the next-step card is visible in the reference viewport. Small card-bottom and composer offsets remain cosmetic. |
| Colors | Blue actions/selection, neutral surfaces, green status and blue/purple chart series preserve the selected direction. Both synthetic chart bands are visible. |
| Assets | Tabler icons and a real Chart.js canvas are used, not a screenshot masquerading as UI. Brand and assistant glyphs are library approximations rather than exact reference artwork; this is a P3 cosmetic difference. |
| Copy | The selected research content and observation-versus-conclusion distinction remain. Persistent demo labeling, explicit synthetic responses and the added return-to-platform action accurately explain the prototype. Chart bands are described as synthetic illustration, not measured confidence intervals. |

The narrow screenshot has no visible page-level horizontal overflow and retains platform return, resource access, project creation and assistant access. The floating assistant button overlaps part of the scrollable chart at the initial position; it does not cover the primary navigation or creation action. Detailed interaction assertions come from the browser run below, not from a still screenshot alone.

## Findings closed by the reviewed revision

1. **P2: undersized text and chart geometry.** The revised fonts, button width, chart inset and synthetic range fills were rechecked in the new same-viewport render.
2. **P2: resetting the wrong project's conversation.** `ResearchDemo.tsx` now uses `initialProjectMessages(project?.id)` on project changes and explicit reset. The session test covers the non-inference project; the browser script covers a newly created project.
3. **P2: platform resource navigation redirected to research.** The special ResourceCenter now requires the existing restricted `modelReturn=research` context. Explicit platform navigation clears that context. Ordinary platform resources use the original Pages implementation. The browser script exercises platform and application origins plus model/connection return navigation.
4. **P2: logout errors disappeared inside the application shell.** Existing `sessionError` and `sessionBusy` are passed through; the demo shows an alert and disables logout while busy. A component test checks both error visibility and the existing logout callback. There is no second authentication controller.
5. **Unrelated dependency churn.** The lockfile now retains existing libc metadata; changes are limited to the selected icon/chart dependencies and their required packages.
6. **Console evidence gap.** The browser script now records both console errors and page errors. Iteration 3 exposed duplicate sibling React keys in the existing connection page. The two keys are now `ssh:${user.id}` and `credentials:${user.id}`, retaining owner-based remounting without a new state mechanism. Iteration 4 records both error arrays empty.

## Simplification and boundary review

The optional application view slot is a concrete consumer-driven addition to the existing Workspace. The demo uses the same session controller and URL/history machinery. The explicit demo entry and Vite mode leave the default core composition without installed research UI. App-only rendering/data stay in the application directory; the architecture map names the composition exceptions.

The resource-origin handling reuses the existing bounded return pointer; it does not introduce a second router. Shared connection keys receive only the necessary sibling-identity correction. Synthetic projects are scoped by the current user in session storage. Demo messages and records remain fixed fixtures; file selection retains only a local filename. No new task dispatch, credential store, retry loop, recovery state machine or research backend write is introduced.

**P3 maintainability:** `web/apps/research-demo/demo.css:120–140` contains visual-tuning overrides of earlier declarations. These are bounded to this demo, but folding final values into the original rules would make future styling easier to inspect. No extra abstraction or styling framework is warranted. This does not block the clickable demo.

## Evidence and limits

- `/tmp/af-research-demo-evidence/interaction-4/browser.json`: two Chromium viewports passed; both `page_errors` and `console_errors` are empty; recorded non-auth write calls are empty.
- The script uses synthetic HTTP identity/core fixtures. It exercises project/deep-link refresh, browser history, dialogs and focus restoration, new-project owner isolation, conversation reset, resource-origin navigation and logout/relogin. This is real browser execution against synthetic data, not real authentication or research execution.
- Session and route test source was inspected, including the logout-error/busy and current-project reset regressions. Author reports 448 Web tests passed and a separate demo build succeeded; those commands were not rerun by this reviewer.
- `git diff --check` completed successfully during review. The worktree was clean at the reviewed code head before adding this report.
- Preserve iteration 1 findings and iteration 3 console failure alongside iteration 4 success. A successful later run does not erase those findings.
- Real core/OIDC integration evidence is a separate coordinator-owned check. External production identity, real models, scientific outcomes, GPU behavior and formal UI acceptance are outside this review.

The local screenshot paths identify the evidence inspected here. Copy the chosen screenshots into the delivery evidence or a durable attachment before presenting them as user-accessible deliverables.
