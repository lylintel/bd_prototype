import argparse
import json
import platform
import random
from statistics import median
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


def benchmark(*, instance_count=2000, connections_per_instance=4, seed=20261112, samples=11):
    if type(samples) is not int or not 10 <= samples <= 100:
        raise ValueError("samples must be between 10 and 100")
    document, library = synthetic_design(instance_count=instance_count, connections_per_instance=connections_per_instance, seed=seed)
    durations = []
    for _ in range(samples):
        started = perf_counter()
        diagnostics = validate(document, library)
        durations.append((perf_counter() - started) * 1000)
        if diagnostics:
            raise AssertionError([item.to_dict() for item in diagnostics])
    return {"instances": instance_count, "connections_per_instance": connections_per_instance, "nets": len(document["nets"]),
            "seed": seed, "samples_ms": durations, "min_ms": min(durations), "median_ms": median(durations), "max_ms": max(durations),
            "python": platform.python_version(), "platform": platform.platform(), "processor": platform.processor()}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Benchmark full in-memory semantic validation")
    parser.add_argument("--instances", type=int, default=2000)
    parser.add_argument("--connections", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20261112)
    parser.add_argument("--samples", type=int, default=11)
    parser.add_argument("--median-ms", type=float, default=300)
    parser.add_argument("--max-ms", type=float, default=600)
    args = parser.parse_args(argv)
    result = benchmark(instance_count=args.instances, connections_per_instance=args.connections, seed=args.seed, samples=args.samples)
    print(json.dumps(result, indent=2))
    return 0 if result["median_ms"] < args.median_ms and result["max_ms"] < args.max_ms else 1


if __name__ == "__main__":
    raise SystemExit(main())