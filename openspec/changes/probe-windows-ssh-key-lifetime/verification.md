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

## First actual Windows experiment — candidate rejected

[Run 40236604542](https://github.com/Guanzhw/agent-factory/actions/runs/40236604542), job 121299416714, PR #138 head `d585e6c56c2ff35a869b8927ae8e701f8a740cca`; checkout was the PR merge `e99eb453aaed6d20b1ab1ee6857b9a4bb0be48e1`. Windows Server 2025 / 10.0.26100, Python 3.12.10, system OpenSSH 9.5p2. Exact safe JSON from the job log:

```json
{"candidateAccepted":false,"cases":{"forced":{"errorCode":"KEY_LOADER_REJECTED","fixtureComplete":true,"keeperExitCode":1,"keyAbsentAfterExit":false,"loaderExitCode":255,"readable":false,"stage":"LOADER_COMPLETE","terminatedWhileKeeperAlive":true},"normal":{"errorCode":"KEY_LOADER_REJECTED","fixtureComplete":true,"keeperExitCode":0,"keyAbsentAfterExit":true,"loaderExitCode":255,"readable":false,"stage":"LOADER_COMPLETE"}},"experimentCompleted":true,"sshVersion":"OpenSSH_for_Windows_9.5p2","windowsVersion":[10,0,26100]}
```

[Preserved artifact 12615456111](https://github.com/Guanzhw/agent-factory/actions/runs/40236604542/artifacts/12615456111). Both real loader calls failed. Normal close removed the key; immediate post-TerminateProcess absence failed. The latter is an observed failure at the stated boundary, not proof of indefinite residue or a diagnosed kernel mechanism. No raw stderr was retained, so sharing incompatibility remains the source-supported explanation, not a directly measured Win32 loader error. The final owned-directory cleanup returned without a reported error. No protection flag was relaxed and no retry was performed.

The Actions step reported exit 1 despite the completed rejection's Python return 2. Logs show `pwsh -command ". '{0}'"`: this invokes a script as the last command. PowerShell documents conversion of a called script's nonzero/non-one exit into host exit 1 under `-Command`; preserving it requires outer `exit $LASTEXITCODE`, or `-File`. See [about_Pwsh](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_pwsh#-command--c). This explains the harness status without changing the rejected candidate's JSON. No local pwsh is installed, so no standalone shell reproduction was run. Any future harness adjustment should preserve a numeric probe-exit receipt and retain this first result; it does not justify rerunning this candidate.
