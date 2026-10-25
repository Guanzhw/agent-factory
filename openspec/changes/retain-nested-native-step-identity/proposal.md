> 状态：已撤回的诊断方案，仅保留历史证据。真实嵌套恢复复验仍失败，应用已改用扁平 native steps；本分支中的探索性 core 修改已还原。本 change 不是当前待实现/验收要求，不据下列旧计划宣称嵌套恢复已修复。详见 `../restore-team-research-application/native-workflow-verification.md`。

# Why

A real nested Router/Steps workflow paused on an original external operation, then failed its decision-agent continuation identity check. Agno preserved the declaration ID in the original executor run and response while its persisted requirement carried a runtime UUID. The child operation had already completed; repeated submission is not a repair.

# What Changes

Accept this evidenced representation only when the response's step ID equals the registered declaration ID and the original persisted requirement matches the registered name, agent and exact executor run. Preserve all original workflow/session/owner/ticket/child identity checks and the existing runtime-UUID path.

# Impact

Core native workflow identity validation and focused regressions. No second recovery mechanism, changed provider retry, timeout extension or Research import.
