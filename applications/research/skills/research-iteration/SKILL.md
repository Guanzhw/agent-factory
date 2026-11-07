---
name: research-iteration
description: Explore a research question by proposing candidates, using available evaluators and revising the approach from observed results. Use for open-ended experiments or optimization tasks.
---
Start from the user's question and the available environment. Inspect existing files, results, tools and evaluators before building anything. Choose the route yourself; these are suggestions, not required stages.

Make a concrete candidate or hypothesis, run a useful check, read the actual output, and use what you learn to choose the next action. A negative result or ordinary command failure can be useful evidence. Change the candidate, fix a broken evaluator, ask a subassistant, or use another tool when that advances the question. Do not treat a tool error as a requirement to stop all work.

Prefer the task's own evaluator and ordinary files or logs. Record enough detail to reproduce useful results: what changed, the command or evaluator used, relevant inputs, observed outcomes and uncertainties. A Markdown notebook is sufficient. The optional research record tools can retain an observation or analysis; no experiment ID or particular task receipt is needed to begin research.

If an operation has an unknown outcome, report that fact and inspect its existing output or status. Do not automatically repeat a potentially side-effecting operation just to discover whether it happened. Continue independent work when useful. Respect the user's Stop request.

Finish with the result, supporting files and what remains uncertain. Do not invent success or force a preset number of iterations. Read references/choosing-checks.md if you need help selecting a useful next check.
