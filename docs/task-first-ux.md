# Task-first frontend contract

## Primary journey

1. **应用与任务** is the default signed-in entry. Select an approved application, describe the task, and prepare a proposal. The catalog may contain synthetic demonstration apps: their results are not research evidence.
2. Review the goal, selected execution mode, scope, required connections, limits, and missing prerequisites. Accepting a proposal fixes a plan; it does not start execution.
3. Complete the existing server-authoritative review/authorization gate, then explicitly start. Never enable a model/provider, expand permissions, or skip a consequential approval as a UI convenience.
4. Select a task to inspect progress, questions, approval requests, and evidence. Execution completion and scientific validation remain distinct.

**Auto-Research 实验** is the separately configured experimental research runner. It is not the generic seeded Auto-Research application's task composer. With no runner presets, show a reason and usable alternatives: select another approved application, retry configuration discovery, or contact the administrator. Do not fabricate a usable preset.

## Information hierarchy

- Lead with the new task, not a historical proposal inbox or internal architecture.
- Keep required inputs, connections, execution scope, budgets, blockers, and approvals visible.
- Put optional material choices, adapter versions, fingerprints, and raw JSON in closed details sections.
- Group task navigation separately from resource tools and manager-only administration. A hidden manager control is not an authorization boundary; the server remains authoritative.
- Every empty/error state states what happened and offers the next permitted action. Uncertain writes retain their original request identity; retry must not silently create another task.

## Navigation

The existing page uses small URL query pointers rather than a routing framework: `tab`, `task`, and `run`. Reload and Back/Forward restore the selected view and record. Preserve unrelated query parameters and hashes. Unknown tabs and unauthorized admin tabs fall back to the task entry. Passive recovery does not push or replace browser history; opening the recovered record is an explicit action. Record IDs are validated and remain subject to authenticated server reads; never place goals, credentials, proposals, or approval state in the URL.

## Glossary

- **应用**: An approved reusable task definition; choose it before describing work.
- **任务目标**: The user's requested outcome.
- **提案**: A reviewable candidate, not permission to execute.
- **方案**: An immutable accepted proposal, still subject to execution authorization.
- **开始任务**: The explicit operation that requests execution of the authorized plan.
- **资源连接**: A user-owned reference to an authorized service, not a catalog material or credential.
- **进度与结果**: Server records and artifacts; completion alone does not establish correctness.
- **材料 / 适配器**: Advanced implementation details managed through approved definitions.

## Verification scope

Automated tests cover URL parsing/round-trips, role-based view selection, first-entry hierarchy, empty runner alternatives, review-before-start, and existing authorization/recovery contracts. Lint, TypeScript, tests, build, and dependency audit must run against the final tree. Browser screenshot/responsive and real-user usability acceptance remain unverified when no permitted capture path is available. Synthetic tests do not establish live model/ORX compatibility.

## Unchanged runner limits

The experimental runner rereads presets immediately before its first start request and requires another review when the displayed settings changed. The existing start API identifies a preset by ID, not an immutable revision: the browser cannot guarantee atomic configuration pinning between that read and the POST. Existing uncertain requests retain their exact original payload and key. A terminal record is not silently cleared to create a fresh execution; that intent/key lifecycle is outside this UI change.

### Implementation check, 2026-10-08

`npm run check` passes lint, TypeScript, 253 tests across 33 files, and the production build. `npm audit` reports zero vulnerabilities. Mounted React tests use happy-dom with synthetic API fixtures, including review-before-start, denied/unset authorization, uncertain acknowledgement with a subsequently empty catalog, settings refresh failures/changes, owned deep links, reload, and Back/Forward. Independent code review found no remaining material issue after corrections. No live provider calls were made. Vite reports a non-blocking approximately 503 kB bundle-size warning; browser layout and human usability acceptance remain outstanding.
