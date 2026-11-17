from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def performance_status(result, *, strict=False):
    summary = f"median={result['median_ms']:.3f}ms (<300), max={result['max_ms']:.3f}ms (<600)"
    if result["budget_passed"]:
        print(f"PERFORMANCE PASS: {summary}", flush=True)
        return 0
    print(f"*** PERFORMANCE WARNING: {summary}; {'strict failure' if strict else 'advisory only'} ***", flush=True)
    return 1 if strict else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run local functional and performance checks")
    parser.add_argument("--strict-perf", action="store_true")
    args = parser.parse_args(argv)
    npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
    missing = [tool for tool in ("iverilog", "vvp") if not shutil.which(tool)]
    if npm is None:
        missing.append("npm")
    if missing:
        print(f"Missing required tools: {', '.join(missing)}. See README development checks.", file=sys.stderr)
        return 2
    commands = [
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "pytest", "-q", "tests/golden", "tests/semantics"],
        [sys.executable, "-m", "pytest", "-q", "tests/test_builtin_ip.py", "tests/test_ip_parser.py"],
        [sys.executable, "-m", "pytest", "-q", "--ignore=tests/ai", "--ignore=tests/golden", "--ignore=tests/semantics",
         "--ignore=tests/test_builtin_ip.py", "--ignore=tests/test_ip_parser.py"],
        [sys.executable, "-m", "pytest", "-q", "tests/ai"],
        [sys.executable, "-m", "bdstudio.ai_eval", "--client", "mock", "--report", "build/ai-eval"],
        *[[npm, "--prefix", "web", "run", task] for task in ("lint", "typecheck", "test", "build", "test:e2e")],
    ]
    for command in commands:
        print(f"\n> {' '.join(command)}", flush=True)
        try:
            result = subprocess.run(command, cwd=ROOT, timeout=300, env={**os.environ, "BD_PYTHON": sys.executable})
        except (OSError, subprocess.TimeoutExpired) as error:
            print(str(error), file=sys.stderr)
            return 1
        if result.returncode:
            return result.returncode
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.synthetic_design import run_isolated

    try:
        result = run_isolated()
        (ROOT / "build").mkdir(exist_ok=True)
        (ROOT / "build/performance.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return performance_status(result, strict=args.strict_perf)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"Performance measurement failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())