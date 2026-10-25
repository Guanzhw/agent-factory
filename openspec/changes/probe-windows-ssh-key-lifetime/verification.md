# Windows key lifetime probe status

This is an experiment, not a Windows product credential implementation.

- Spec preceded script: 76ad204 (equivalent original e310f52, isolated from SSH product branch).
- Linux static validation: Ruff and Python compile passed.
- Linux invocation correctly returned exit 1 with `experimentCompleted=false`, `candidateAccepted=false`, `errorCode=WINDOWS_REQUIRED`.
- Windows key loading, DACL inspection, forced keeper termination and cleanup: NOT RUN. Independent script review required before CI execution.
- No SSH connection, system service/configuration changes, real key access, or new dependencies.

Run on Windows with the existing project Python environment (cryptography is already a project dependency):

```
python scripts/probe_windows_ssh_key.py
```

Use a CI outer timeout of 60 seconds. Exit 2 is a completed rejected candidate and must retain its JSON evidence; exit 1 is an incomplete experiment. Neither is acceptance. The upstream file sharing mode predicts rejection, which must not be repaired by removing delete-on-close protection. Keep the first actual Windows result.

## Independent review corrections before Windows execution

The first static review found four experiment-quality issues; all were corrected before any Windows execution:
- Private-key ACL inspection uses `GetSecurityInfo` on the keeper handle, avoiding a second filename open that could itself violate delete sharing.
- Expected owner/DACL is canonicalized by the same Windows descriptor conversion as actual metadata; no permission constraint is removed.
- CreateFile's numeric last-error is captured before descriptor cleanup.
- Keeper fixture errors write atomic safe phase/type/numeric-error results, distinct from loader rejection, and the parent retains these in its JSON. No exception message, traceback or raw stderr is emitted.

Actual Windows version metadata and a positive forced-termination-issued observation are included. Static Ruff/compile/diff checks pass; Windows remains NOT RUN pending independent re-review.
