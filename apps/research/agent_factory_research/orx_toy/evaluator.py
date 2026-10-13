"""Original deterministic evaluator. No dependencies, network, providers, or children.

Only three reviewed scenarios are accepted. Own output/wall bounds survive the
Factory process; Windows Job Objects provide aggregate CPU/memory/process caps.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from baseline import predict as baseline
from candidate import predict as candidate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--owner-sha", required=True)
    parser.add_argument("--scenario", choices=("success", "evaluator_failure", "long_running"), required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--output-limit", type=int, required=True)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 30 or not 4096 <= args.output_limit <= 1048576:
        raise SystemExit(2)
    start = time.monotonic()
    print("Reviewed toy evaluation started", flush=True)
    if args.scenario == "long_running":
        # Bounded intentionally cancellable computation; no background child.
        while time.monotonic() - start < min(20, args.timeout - 1):
            print("progress: cancellable evaluator alive", flush=True)
            time.sleep(0.5)
    data = json.loads(Path("dataset.json").read_text(encoding="utf-8-sig"))
    def mse(predict):
        return sum((predict(row["x"]) - row["y"]) ** 2 for row in data) / len(data)
    hashes = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
              for name in ("baseline.py", "candidate.py", "dataset.json", "evaluator.py")}
    failed = args.scenario == "evaluator_failure"
    result = {"schemaVersion": 1, "evidenceKind": "actual_orx_local_toy_evaluation",
              "taskId": args.task, "ownerSha256": args.owner_sha, "scenario": args.scenario,
              "status": "failed" if failed else "done", "sampleCount": len(data),
              "metric": "mean_squared_error", "baseline": {"value": mse(baseline)},
              "candidate": {"value": mse(candidate)}, "improvement": mse(baseline) - mse(candidate),
              "fileSha256": hashes, "zeroModelCalls": True,
              "failureCode": "REVIEWED_EVALUATOR_FAILURE" if failed else None}
    raw = (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(raw) + 4096 > args.output_limit or time.monotonic() - start >= args.timeout:
        raise SystemExit(4)
    Path("result.json").write_bytes(raw)
    print("Evaluation failed deliberately" if failed else "Evaluation completed: baseline MSE=16, candidate MSE=0", flush=True)
    return 3 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
