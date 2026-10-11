# Native research command and result presentation

Reproduced on main `a3fe4a3a2b113d73979226399b96fe9f321dc77b`,
2026-10-11, using Chromium 151 and controlled local fixtures:

* An assistant error message with `completed: true` showed “remote completed”.
  Completion marks the end of a message, not successful research.
* The follow-up field displayed “continue research” but its accessible name was
  “research goal”.
* The task button selected the original session-creation task after a later
  prompt had been admitted and its reply observed.
* A valid native-command receipt with a demo Factory controller caused the task
  headline to label every displayed result synthetic, including separately
  projected remote-reported session records.

The session read response now includes the latest owner-scoped admitted command
identity. It is read from durable command rows with existing integrity checks;
the original creation identity is preserved for recovery and rebind. The task
button uses the latest identity, including after refresh or service reconstruction.

Native terminal error records show failure and no final reply. A recoverable tool
failure followed by readable final text remains a completed reply. Unknown
acknowledgements retain their existing higher-priority warning and prohibit
automatic replay. Follow-up accessible and visible labels agree.

Only receipts matching the task, plan and native-command contract receive the
more precise command source label. Demo command execution remains explicitly
identified, ordinary synthetic tasks retain their synthetic result warning, and
the deployment-level demo/development banner remains unchanged. Remote-reported
records do not establish scientific validity, exact-turn verification, metering,
or confirmed process stop.

All new browser evidence for this patch is synthetic and visibly labeled.
No new real model invocation or native research acceptance is claimed.
