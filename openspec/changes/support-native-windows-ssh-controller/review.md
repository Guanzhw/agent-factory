# PR138 independent complete-diff review

Reviewer: `windows_review`, not an implementation author; Windows primitive cross-check by `windows_review/windows_security`, also not an author.

Exact base: `62614177c23c4d2cd0caf6b7c91418e74fde8ad4`.
Exact reviewed head: `445a2ce89ab2fe38d8269d3f1f6a17bed9a81024`.
Scope: all 50 changed files, including four Windows production modules, both existing SSH consumers and their regressions, installed-wheel runner, probe package/history, packaging/lock, workflow and UI diagnostic.

**Implementation and simplicity review: PASS. Release acceptance remains pending.** No new blocking product defect was found. This is a new review of the stated head, not recovery of the unavailable `51e0c19` commit or an extension of the earlier `41edf268` verdict by assumption.

The change retains the existing vault, scope guards, transport, native custody and original-operation recovery. The Windows boundary has concrete owners: encrypted per-invocation files and one-use broker, explicit stdio handle inheritance, suspended creation followed by Job assignment, fixed helper/interpreter ancestry to the held original SSH process, shared consumer deadline, and failed-cleanup admission closure. These checks address measured lifecycle and credential risks; there is no second executor, generic transport registry, cluster scheduler or persistent credential cache. Both consumers close their explicit scope even when exchange entry fails. Relative `askpass.exe` and `known_hosts` lookup preserve the protected child cwd, exact helper bytes, strict host pin and original interpreter checks. No assertion or timeout was weakened to accept the installed repair.

The isolated mechanism probe remains test-only and is excluded from core packaging. Its historical failure evidence and diagnostic instrumentation are bounded and relevant. Do not copy its raw observations into another report. One non-blocking leftover is the unused public `FACTORY_SSH_KEY` environment field; removing it is optional and does not justify broadening this finalization.

Documentation correction required before release: the active task checkboxes, integration checkpoint and installed/owned-process evidence still contain superseded pending or blocked statements. Add a concise current status with exact CI links and retain the first failures as history. The existing review file also names an older head. The coordinator is preparing this documentation-only correction; its exact increment must receive independent re-review.

Review checks: `git diff --check` passed for the entire stated range; all 19 changed Python files parsed from the exact Git objects. This Linux review did not rerun Windows APIs, dependency audits or full CI. Coordinator-reported Windows run `40247109502` and fast run `40247109535` must be linked as results for `445a2ce`; they do not substitute for final applicable full verification or checks on a later documentation head.

Keep Windows-to-Linux installed-helper original submit/inspect/cancel and lost-ack recovery **BLOCKED/NOT RUN** until an authorized endpoint is exercised. Windows loopback ForceCommand acceptance is narrower. Acetamido, production IdP, real model/GPU execution and GPU binding/isolation are not established; CUDA process capability would not establish allocation or isolation. No merge readiness is granted by this source review alone.

Historical foundation_review verdict: [review at 445a2ce](https://github.com/Guanzhw/agent-factory/blob/445a2ce89ab2fe38d8269d3f1f6a17bed9a81024/openspec/changes/support-native-windows-ssh-controller/review.md).
