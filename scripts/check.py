from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main():
    npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
    missing = [tool for tool in ("iverilog", "vvp") if not shutil.which(tool)]
    if npm is None:
        missing.append("npm")
    if missing:
        print(f"Missing required tools: {', '.join(missing)}. See README development checks.", file=sys.stderr)
        return 2
    commands = [
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "pytest", "-q"],
        *[[npm, "--prefix", "web", "run", task] for task in ("lint", "typecheck", "test", "build")],
    ]
    for command in commands:
        print(f"\n> {' '.join(command)}", flush=True)
        try:
            result = subprocess.run(command, cwd=ROOT, timeout=300)
        except (OSError, subprocess.TimeoutExpired) as error:
            print(str(error), file=sys.stderr)
            return 1
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())