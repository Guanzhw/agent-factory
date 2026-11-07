# Choosing a useful check

Choose a small check that can distinguish the candidate from a baseline. Preserve relevant conditions so a comparison means something. Inspect the evaluator before trusting its metric: what does it measure, which direction is better, and what data does it use?

Use an existing local command, remote environment, MCP tool or a subassistant when appropriate. Resource availability may determine the route. If a proposed run is impractical, choose another useful check or explain what is missing.

A failed command is not a negative scientific result unless the failure itself tests the hypothesis. Keep stderr and exit status, correct the execution problem and then interpret the outcome. Do not require a shared result schema; retain the evaluator's original output.
