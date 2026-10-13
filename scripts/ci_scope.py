"""Select docs/fast CI from changed paths; only manual dispatch selects full."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess


ROOT_DOCS = {"README.md", "ARCHITECTURE.md", "AGENTS.md", "CHANGELOG.md", "CONTRIBUTING.md"}
JOBS = ("scope", "frontend", "python", "postgres")


def docs_path(path):
    return (path in ROOT_DOCS or path == ".github/pull_request_template.md"
        or bool(re.fullmatch(r"docs/(?:[^/]+/)*[^/]+\.md", path)))


def comparison(event_name, event):
    if not isinstance(event, dict):
        return None
    if event_name == "pull_request":
        pull = event.get("pull_request")
        if not isinstance(pull, dict):
            return None
        base, head = pull.get("base"), pull.get("head")
        if not isinstance(base, dict) or not isinstance(head, dict):
            return None
        before, after, separator = base.get("sha"), head.get("sha"), "..."
    elif event_name == "push" and not event.get("created"):
        before, after, separator = event.get("before"), event.get("after"), ".."
    else:
        return None
    if any(not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", sha)
           or sha == "0" * 40 for sha in (before, after)):
        return None
    return before + separator + after


def classify(event_name, event):
    if event_name == "workflow_dispatch":
        return "full", None
    revision_range = comparison(event_name, event)
    if revision_range is None:
        return "fast", None
    try:
        result = subprocess.run(["git", "diff", "--name-only", "-z", "--no-renames", revision_range, "--"],
            capture_output=True, check=False)
    except OSError:
        return "fast", None
    if result.returncode:
        return "fast", None
    paths = [os.fsdecode(path) for path in result.stdout.split(b"\0") if path]
    return ("docs" if paths and all(docs_path(path) for path in paths) else "fast"), revision_range


def write_environment_file(variable, text):
    if os.environ.get(variable):
        with Path(os.environ[variable]).open("a", encoding="utf-8") as output:
            output.write(text)


def summarize(needs, event_name):
    needs = needs if isinstance(needs, dict) else {}
    jobs = {name: needs.get(name) if isinstance(needs.get(name), dict) else {} for name in JOBS}
    outputs = jobs["scope"].get("outputs")
    mode = outputs.get("mode") if isinstance(outputs, dict) else None
    valid_mode = mode in {"docs", "fast", "full"} if isinstance(mode, str) else False
    errors = []
    if not valid_mode:
        errors.append("Scope did not report a recognized mode.")
    if (mode == "full") != (event_name == "workflow_dispatch"):
        errors.append("workflow_dispatch must use full mode, and other events cannot use full mode.")
    rows = []
    for name, job in jobs.items():
        expected = "skipped" if mode == "docs" and name != "scope" else "success"
        result = job.get("result")
        if result != expected:
            errors.append(f"{name} must finish as {expected}.")
        displayed = result if result in ("success", "failure", "cancelled", "skipped") else "missing/invalid"
        rows.append(f"| {name} | {displayed} | {expected} |")
    report = (f"CI mode: **{mode if valid_mode else 'unknown'}**\n\n"
        "Full verification runs only on `workflow_dispatch`; fast checks do not replace full verification.\n\n"
        "| Job | Result | Required |\n| --- | --- | --- |\n" + "\n".join(rows) + "\n\n"
        + ("CI result: passed.\n" if not errors else "CI result: failed.\n\n" + "\n".join("- " + error for error in errors) + "\n"))
    return not errors, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", action="store_true", help="Validate job outcomes supplied through CI_NEEDS")
    args = parser.parse_args(argv)
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    if args.summary:
        try:
            needs = json.loads(os.environ.get("CI_NEEDS", ""))
        except ValueError:
            needs = None
        accepted, report = summarize(needs, event_name)
        write_environment_file("GITHUB_STEP_SUMMARY", report)
        print(report, end="")
        return 0 if accepted else 1
    try:
        event = json.loads(Path(os.environ.get("GITHUB_EVENT_PATH", "")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        event = None
    mode, revision_range = classify(event_name, event)
    operating_systems = ["ubuntu-latest", "windows-latest"] if mode == "full" else ["ubuntu-latest"]
    output = f"mode={mode}\nos={json.dumps(operating_systems)}\n"
    write_environment_file("GITHUB_OUTPUT", output)
    print(output, end="")
    if mode == "docs":
        return subprocess.run(["git", "diff", "--check", revision_range, "--"], check=False).returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
