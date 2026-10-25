# Why

A real nested Router/Steps workflow paused on an original external operation, then failed its decision-agent continuation identity check. Agno preserved the declaration ID in the original executor run and response while its persisted requirement carried a runtime UUID. The child operation had already completed; repeated submission is not a repair.

# What Changes

Accept this evidenced representation only when the response's step ID equals the registered declaration ID and the original persisted requirement matches the registered name, agent and exact executor run. Preserve all original workflow/session/owner/ticket/child identity checks and the existing runtime-UUID path.

# Impact

Core native workflow identity validation and focused regressions. No second recovery mechanism, changed provider retry, timeout extension or Research import.
