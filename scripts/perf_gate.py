import argparse
import json
import os
from pathlib import Path

from scripts.synthetic_design import run_isolated


def collect_runs(count=5):
    if type(count) is not int or not 5 <= count <= 20:
        raise ValueError("at least five benchmark runs are required")
    runs = []
    for index in range(count):
        result = run_isolated()
        runs.append(result)
        print(f"PERF {index + 1}: median={result['median_ms']:.3f} max={result['max_ms']:.3f} ms", flush=True)
    if len({result["design_sha256"] for result in runs}) != 1:
        raise RuntimeError("benchmark designs differ")
    return {"schema_version": 1, "runs": runs, "non_blocking": any(not result["budget_passed"] for result in runs)}


def write_summary(report, destination):
    first = report["runs"][0]
    rows = ["## Validation Performance", "", "User-approved budgets: median <300ms, max <600ms; 11 samples per fresh process.",
            f"Python {first['python']} / {first['platform']} / {first['processor']} / {first['cpu_count']} logical CPUs.", "",
            "| Run | Median ms | Max ms | Within Budget |", "| --- | --- | --- | --- |"]
    rows.extend(f"| {index} | {result['median_ms']:.3f} | {result['max_ms']:.3f} | {result['budget_passed']} |"
                for index, result in enumerate(report["runs"], 1))
    rows.extend(["", "Non-blocking: at least one of the five runs exceeded budget; retaining all data."
                 if report["non_blocking"] else "Blocking budget gate: all five calibration runs are within budget.", ""])
    with Path(destination).open("a", encoding="utf-8") as stream:
        stream.write("\n".join(rows))


def enforce(report):
    return 0 if all(result["budget_passed"] for result in report["runs"]) else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Collect and enforce the user-approved CI performance policy")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output")
    mode.add_argument("--check")
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args(argv)
    if args.check:
        return enforce(json.loads(Path(args.check).read_text(encoding="utf-8")))
    report = collect_runs(args.runs)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        write_summary(report, os.environ["GITHUB_STEP_SUMMARY"])
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            stream.write(f"non_blocking={str(report['non_blocking']).lower()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())