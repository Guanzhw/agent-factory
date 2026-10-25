# Real loopback SSH process mechanism

2026-10-25. CPU-only, synthetic commands; no model, GPU, external server or
production deployment was used. Test added on parent
`528fac92609e902544a5d96725e3e2c227a9969c`; this record and the test are the only
files in this verification change. Other workers' product changes were present
in the shared checkout: the result is a mechanism check, not exact-commit full
integration acceptance. Independent review is pending.

## Fixture and command

```sh
PYTHONPATH=platform /workspace/agent-factory-research-next/.venv/bin/python \
  -m unittest discover -s platform/tests -p test_ssh_process_loopback.py -v
```

The local runner uses the checkout imports. The remote helper does **not** use
PYTHONPATH: the fixture builds the current standalone core wheel offline,
installs it into a disposable venv, reuses the runner's installed dependency
site-packages, verifies the package resolves inside that venv, and invokes
`python -I -B -m agent_factory.ssh_process_helper` over actual OpenSSH.

The existing nonroot `agent` account runs a temporary ssh-agent and sshd. Both
the backend and transparent TCP entrance listen only on `127.0.0.1`, on dynamic
non-22 ports. Host/client/wrong-host keys are generated only inside a temporary
0700 directory; private-key modes are checked as 0600. No account or system SSH
configuration is changed. The temporary sshd uses `StrictModes no` because
OpenSSH rejected the world-writable `/tmp` ancestor of its private authorized-key
directory. Product `StrictHostKeyChecking=yes` remains unchanged. This fixture
does not certify production sshd configuration or account authentication.

## Observed result and assertions

The corrected fixture ran **1 test, 1 passed, 0 skipped, 8.935 seconds, exit 0**.
The local log is `/tmp/af-ssh-loopback-cancel.log` (not a portable artifact).

- Wrong final-host pin fails through the relay before any custody directory is
  created. Correct pin reaches the installed helper; capability response reports
  process custody and explicitly no GPU allocation.
- Real submit reaches `COMPLETED` with positive stopped proof. A fresh transport
  inspects the same custody. Duplicate submit retains the original custody ID
  and child identity; there is exactly one run directory.
- Output is exactly the synthetic command's bytes and its matching SHA-256.
- A second bounded command receives cancellation. The receipt retains the
  original ID and `cancelRequested`; bounded inspection observes the same ID
  with stopped proof and `CANCELLED`. A cancel acknowledgement alone is not
  counted as stopped proof.

After that passing run, only fixture logging was narrowed (`LogLevel ERROR`,
omit ssh-agent environment output) and the module's scope/command documentation
was clarified. No new browser/SSH execution is claimed for those final edits.
Final Ruff and `git diff --check` passed. A process listing found no surviving
`af-ssh-loopback-` process; context cleanup removed the temporary keys, wheel,
venv, custody files and sockets. The serial resource window was released.

## First failures retained

These are diagnostic iterations, not discarded successful-run prerequisites:

1. `af-ssh-loopback-first.log`: wheel setup failed; initial helper hid subprocess
   stderr. Build selection was also corrected to the standalone core directory.
2. `af-ssh-loopback-second.log`: explicit stderr identified read-only default uv
   cache. The fixture now owns its temporary cache, with no network resolution.
3. `af-ssh-loopback-third.log` and `fourth.log`: ssh-agent could not bind its Unix
   socket under the default sandbox. The fourth records `Operation not
   permitted`. The explicitly authorized local-network execution permission was
   then used; no system permissions/configuration were changed.
4. `af-ssh-loopback-network.log` and `diagnostic.log`: actual sshd refused public
   key authentication due to `/tmp` ownership/mode checks. The diagnostic log
   preserves that cause; only the temporary fixture config changed as above.
5. `af-ssh-loopback-keydir.log`: submit, output and duplicate identity checks
   succeeded, but the test incorrectly required immediate stopped proof from
   cancel. It now follows the existing asynchronous contract: assert cancellation
   intent, then inspect the original identity within the unchanged test bound.
   No product timeout, cancellation rule or terminal assertion was relaxed.

The logs named above remain local under `/tmp/`; this summary does not claim
they have been published. No private-key bytes are included in this record.

## Remaining boundaries

This one test does not inject a lost submit ACK, break an in-flight connection,
restart the controller service, exercise runtime budget admission or an actual
GPU. New SSH helper processes and a fresh client transport do not substitute for
controller restart acceptance. Those scenarios remain separate pending gates;
the real-loopback result must not mark the complete SSH task or D01 passed.
