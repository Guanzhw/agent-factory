# DSH chat-detail design QA

final result: passed

This result covers the second local chat-detail correction on 2026-11-08, based on `37af529552d4e739ef465b274173cb7a4bb80335` and the current local diff. All 23 Windows regressions pass in 125.435 seconds, including the final idle Stop condition and its new pending-request regression. Frontend lint, TypeScript, build, Ruff, Pyright and whitespace checks pass. Independent source review has no remaining confirmed blocker. This report records local visual and Windows acceptance. Publication and exact-head CI are tracked in the PR; merge and deployment remain separate.

## Workflow and reference

Product Design preflight, audit, source-based implementation and design QA were applied to the existing app. Preflight found no saved user-context entries. The in-app browser reaches DSH authentication; the existing authenticated Edge profile supplies the reference without changing authentication.

The reference is installed DSH Web `0.2.2-rc.1` at `http://127.0.0.1:3080/`. Its readable installed `lib/client.js` modules preserve original component/CSS region names. The original TSX/CSS files are absent from those package roots. MIT notices remain in `THIRD_PARTY_NOTICES.md`.

The implementation is the retained Factory preview at `https://127.0.0.1:3100/`. Its frontend is rebuilt without restarting the backend or interrupting the existing running session. The isolated suite starts the current source with Agno 3.1.0, disposable PostgreSQL and a scripted HTTP model.

The earlier Library red-box image is unavailable through the exposed materialization tools. Its annotations were relayed by the coordinating chat; this run does not claim to have inspected its pixels. The live DSH page and installed source establish the corrections below.

## Comparison and corrections

Desktop frames use a 1280 × 900 CSS viewport and device scale 1; tablet frames use 768 × 1024 and phone frames 390 × 844. Source and Factory screenshots were viewed together at equal scale. The reference has two completed synthetic-marker turns and Factory has one short completed real turn, so text length and turn count differ. Vertical message positions are compared after accounting for line count.

| Surface | Reproduced mismatch | Final check |
| --- | --- | --- |
| Header | Snapshot line, body metadata and idle Stop occupied about 133px. | Independent 76px header; ordinary status/configuration moves into session information. Active Stop remains in the composer; session information retains idle Stop for cancelling future collaboration. |
| User message | Bubble radius, message spacing and time/copy row differed. | 20px bubble, 14px/22px text, 6px row gap, 28px desktop copy row and 8px metadata gap. Correction/pending meaning remains visible. |
| Process | Empty right-hand “execution process” text and a 36.8px row. | One real activity label, adjacent disclosure and actual failure count; desktop row measures 33px. Original events/tools remain inside the process. Unknown/child failures remain outside the fold. |
| Management sections | Raw records, questions and an empty file section remained under every reply. | Raw records move inside the process. Native right-side popovers expose files, questions and information. File/question problems remain visible outside closed panels. Empty files show their state directly after opening. |
| Composer | Hint and static model text occupied the control row; card geometry drifted. | 856px maximum card width, 98px desktop height, 28px radius and 36px editor. Desktop card top is 772px, matching DSH. Real model-settings entry, existing commands, send and active Stop work. |
| Short scrolling | Clicking a summary displayed Jump despite zero overflow. | Short live page has scroll/client height 824/824 and no jump after expansion. Jump uses actual distance from bottom. |
| Long scrolling | Details and live content must preserve reading position. | Existing copy, growth, retained-fragment streaming, reading-position and resume-following assertions pass. Header geometry stays fixed. One conversation scroller retains live tool visibility. |
| Responsive layout | Tablet kept a 280px sidebar; mobile added a separate navigation row. A long title later exposed 396px content at a 390px viewport. | Installed source supplies 1024px auto-collapse and 768px drawer boundaries. Tablet uses a 56px folded rail; phone header stays at y=0, height 76px. The owning grid uses `minmax(0, 1fr)`; the long-title/file journey has no document overflow. Mobile primary/icon targets retain 44px access. |

The fonts, dark surfaces, muted text, borders, card shape and existing Tabler icons were checked against the reference. Factory retains its branding and real navigation/capabilities. No imagery is needed for the changed chat detail. Native popovers support Escape and real buttons; question links reopen after either X or Escape. Model-setting navigation preserves a draft. Text/code copying, wrapping and file downloads remain covered.

## Evidence

Private screenshots and logs are outside Git under `D:/WorkSpace/agent-factory-local/design-evidence/chat-details-round2-20261108/`.

| Evidence | State |
| --- | --- |
| `02-factory-hi-before-desktop.png`, `05-factory-hi-before-narrow.png` | Before this correction. |
| `14-dsh-short-accepted-desktop.png`, `13-factory-hi-accepted-desktop.png` | Final equal-scale desktop comparison. |
| `10-dsh-short-tablet.png`, `12-factory-hi-final-tablet.png` | Tablet reference and corrected folded layout. |
| `04-dsh-short-narrow.png`, `15-factory-hi-accepted-narrow.png` | Phone reference and final short conversation. |
| `ui-fixture-waiting.png`, `ui-fixture-unknown.png`, `ui-fixture-reconciled.png` | Explicit scripted UI snapshots: active wait, transport loss, unknown result and reconciliation. |
| `chat-detail-mobile.png`, `ui-fixture-mobile.png` | Long/active and reconciled narrow states. |
| `partial-files.png`, `files-mobile.png` | Native failed tool count, partial file error, recovered files and long-title narrow geometry. |
| `full-regression-attempt1.log`, `focused-files-attempt3.log` | Retained failures: two old selectors and the reproduced 396px grid overflow. |
| `publish-validation/full-final.log`, `publish-validation/frontend-final.log` | Final 23-case result, including pending-request Stop, and frontend checks. |

## Boundaries

The session backend binds a model connection at creation. The model button opens the existing model settings; this round adds no pretend in-session connection switch, usage meter, ratings or branch action. DSH permission/plan/team controls have no matching Factory operation and are not fabricated. Files and colleague questions retain Factory semantics.

No new provider or remote SSH call is needed for these frontend changes. Previous real subscription/SSH/file acceptance remains historical evidence in [joint integration notes](docs/reviews/dsh-skills-integration-20261108.md), including the user's manual Save and byte-exact Edge download confirmation. Current running/error snapshots use synthetic data, and do not establish a new real-provider recovery result. The final pending-request regression disables new composition while a request remains unconfirmed, then clicks the allowed idle Stop and verifies the persisted stopped state without another model call. Restoring the old disable condition makes this test fail at the enabled assertion; the final busy-only condition passes in the complete suite. The red log is retained at `publish-validation/idle-stop-red.log`.

Existing global CSS syntax warnings, bundle-size warnings and Windows TLS/RST/unclosed-transport warnings remain. The suite retains its bounded shutdown check and reports the 35-second graceful timeout with zero active request tasks before the worker stops. Source extensions, including SVG, total 24,097 physical lines across 142 tracked files. Temporary viewport overrides are restored after capture; the isolated test database is stopped after validation.
