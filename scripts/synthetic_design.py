import argparse
import faulthandler
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
from statistics import median
import subprocess
import sys
from time import perf_counter

from bdip import IpMetadata
from core.semantic import validate


def synthetic_design(*, instance_count=2000, connections_per_instance=4, seed=20261112):
    if (type(instance_count) is not int or not 1 <= instance_count <= 20000
            or type(connections_per_instance) is not int or not 1 <= connections_per_instance <= 16
            or instance_count * connections_per_instance > 100000 or type(seed) is not int):
        raise ValueError("invalid synthetic design size or seed")
    metadata = IpMetadata.from_dict({
        "schema_version": 1, "id": "synthetic_cell", "version": "1.0.0", "display_name": "synthetic_cell",
        "description": "In-memory validation benchmark; no executable RTL", "tags": ["synthetic"],
        "source": {"kind": "verilog", "path": "synthetic_cell.v", "sha256": "0" * 64, "license": "MIT"},
        "language": "verilog-2005", "parameters": [{"name": "WIDTH", "type": "int", "default": "8", "min": 1, "max": 32}],
        "ports": [{"name": f"{prefix}_{channel}", "dir": direction, "width": "WIDTH", "range": ["WIDTH-1", 0]}
                  for prefix, direction in (("input", "in"), ("output", "out")) for channel in range(connections_per_instance)],
        "interfaces": [],
    })
    instances = [{"name": f"unit_{index}", "ip": {"id": metadata.id, "version": metadata.version}, "params": {"WIDTH": 8}}
                 for index in range(instance_count)]
    generator = random.Random(seed)
    nets = []
    for channel in range(connections_per_instance):
        order = list(range(instance_count))
        generator.shuffle(order)
        for position, source in enumerate(order):
            target = order[(position + 1) % instance_count]
            nets.append({"name": f"net_{channel}_{source}", "endpoints": [
                {"inst": f"unit_{source}", "port": f"output_{channel}"},
                {"inst": f"unit_{target}", "port": f"input_{channel}"},
            ]})
    return {"schema_version": 2, "name": "synthetic_bd", "ports": {}, "instances": instances, "nets": nets}, (metadata,)


def processor_name():
    if sys.platform.startswith("linux"):
        try:
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
                key, separator, value = line.partition(":")
                if separator and key.strip() == "model name":
                    return value.strip()
        except OSError:
            pass
    return platform.processor() or platform.machine()


def runtime_hooks():
    monitoring = getattr(sys, "monitoring", None)
    coverage = sys.modules.get("coverage")
    coverage_class = getattr(coverage, "Coverage", None)
    return {"trace": type(sys.gettrace()).__name__ if sys.gettrace() is not None else None,
            "profile": type(sys.getprofile()).__name__ if sys.getprofile() is not None else None,
            "faulthandler": faulthandler.is_enabled(),
            "coverage_active": bool(coverage_class and coverage_class.current()),
            "monitoring": {str(index): {"name": monitoring.get_tool(index), "events": monitoring.get_events(index)}
                           for index in range(6) if monitoring and monitoring.get_tool(index) is not None},
            "loaded_instrumentation": sorted(name for name in ("coverage", "pytest_cov", "pytest", "debugpy", "pydevd", "ddtrace") if name in sys.modules),
            "instrumentation_env_present": [name for name in ("COVERAGE_PROCESS_START", "PYTEST_ADDOPTS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD") if os.environ.get(name)]}


def benchmark(*, instance_count=2000, connections_per_instance=4, seed=20261112, samples=11, gc_mode="on"):
    if type(samples) is not int or not 11 <= samples <= 100:
        raise ValueError("samples must be between 11 and 100")
    if gc_mode not in ("on", "off"):
        raise ValueError("gc_mode must be on or off")
    document, library = synthetic_design(instance_count=instance_count, connections_per_instance=connections_per_instance, seed=seed)
    fingerprint = hashlib.sha256(json.dumps({"design": document, "library": [item.to_dict() for item in library]}, sort_keys=True).encode()).hexdigest()
    durations = []
    was_enabled = gc.isenabled()
    try:
        (gc.enable if gc_mode == "on" else gc.disable)()
        for _ in range(samples):
            gc.collect()
            started = perf_counter()
            diagnostics = validate(document, library)
            durations.append((perf_counter() - started) * 1000)
            if diagnostics:
                raise AssertionError([item.to_dict() for item in diagnostics])
    finally:
        (gc.enable if was_enabled else gc.disable)()
    return {"schema_version": 1, "instances": instance_count, "connections_per_instance": connections_per_instance, "nets": len(document["nets"]),
            "seed": seed, "samples_ms": durations, "min_ms": min(durations), "median_ms": median(durations), "max_ms": max(durations),
            "python": platform.python_version(), "platform": platform.platform(), "processor": processor_name(),
            "cpu_count": os.cpu_count(), "pid": os.getpid(), "gc_mode": gc_mode, "collect_before_sample": True,
            "design_sha256": fingerprint, "hooks": runtime_hooks()}


def run_isolated(*, instance_count=2000, connections_per_instance=4, seed=20261112, samples=11, gc_mode="on"):
    command = [sys.executable, "-m", "scripts.synthetic_design", "--instances", str(instance_count), "--connections", str(connections_per_instance),
               "--seed", str(seed), "--samples", str(samples), "--gc", gc_mode]
    completed = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True, encoding="utf-8",
                               timeout=120, env={**os.environ, "PYTHONUTF8": "1"})
    try:
        result = json.loads(completed.stdout)
        durations = result["samples_ms"]
        expected = {"schema_version": 1, "instances": instance_count, "connections_per_instance": connections_per_instance,
                    "nets": instance_count * connections_per_instance, "seed": seed, "gc_mode": gc_mode, "collect_before_sample": True}
        if (not isinstance(durations, list) or len(durations) != samples
                or any(type(value) not in (float, int) or not math.isfinite(value) or value < 0 for value in durations)
                or any(result.get(key) != value for key, value in expected.items())
                or result["median_ms"] != median(durations) or result["max_ms"] != max(durations)
                or result["budget_passed"] is not (result["median_ms"] < 300 and result["max_ms"] < 600)
                or completed.returncode != (0 if result["budget_passed"] else 1)):
            raise ValueError("invalid benchmark result")
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError(f"Benchmark subprocess failed: {completed.stderr[-2000:]}") from error
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Benchmark full in-memory semantic validation")
    parser.add_argument("--instances", type=int, default=2000)
    parser.add_argument("--connections", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20261112)
    parser.add_argument("--samples", type=int, default=11)
    parser.add_argument("--gc", choices=("on", "off"), default="on")
    parser.add_argument("--median-ms", type=float, default=300)
    parser.add_argument("--max-ms", type=float, default=600)
    args = parser.parse_args(argv)
    result = benchmark(instance_count=args.instances, connections_per_instance=args.connections, seed=args.seed, samples=args.samples, gc_mode=args.gc)
    result["budget_passed"] = result["median_ms"] < args.median_ms and result["max_ms"] < args.max_ms
    print(json.dumps(result, indent=2))
    return 0 if result["budget_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())