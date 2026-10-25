# Exact completed-child removal case

Historical full run 40228654327 at 624bf82 failed on delegated custody `COMPLETED != FAILED`. The historical probe did not capture the child stop seal. Read-only deterministic two-sequence proof (`/tmp/af-removal-two-sequences.py`, `/tmp/af-removal-two-sequences.log`) uses real lifecycle fact classification and delegated observation with synthetic I/O: a completed native ticket plus later protected failure is FAILED before a stop seal, but retains COMPLETED after the immutable completed seal. This proves the dependency, not the precise historical scheduling.

Spec clarification abbf523 precedes test correction c424c84. No product changes; original 30-second condition deadline, parent failure/cancellation, identity, holds, positive stop, scope settlement and unchanged research domain assertions remain. The new precondition requires a completed child ticket and persisted `stoppedStatus=completed`; child terminal may remain false while its root owns group completion. Custody then must be exactly COMPLETED with original child task/run, never either-of-two accepted states.

First authorized PG execution: `PYTHONPATH=platform:platform/tests:deployment:applications:applications/tests timeout 120 /workspace/agent-factory-core-only/.venv/bin/python -m unittest test_research_removal_postgres.ResearchRemovalPostgresTests.test_original_task_stops_without_replay_or_research_completion_after_app_removal`, with existing isolated PG fixture URL.

**1/1 passed, zero skipped, 25.333 seconds, exit 0.** Log `/tmp/af-removal-sealed-child-first.log`; preserved synthetic state `/tmp/af-removal-sealed-child-first-evidence.json`. Child before removal: terminal=false, stoppedStatus=completed. Parent after removal: native cancelled, terminal=true, lastStatus=failed; delegated operation COMPLETED; scope SETTLED. Original IDs and research-domain nonmutation assertions all passed. Test subprocesses and isolated database cleaned normally. No second execution was made.

This proves this fixed completed-child scenario, not removal before a child stop seal, every removal interleaving, production identity, or live research/model/GPU behavior.
