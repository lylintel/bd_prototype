import argparse
import hashlib
import json
import math
from pathlib import Path

from bdip import IpMetadata
from core.semantic import validate
from scripts.synthetic_design import synthetic_design


def write_fixture(directory, count, *, seed=20261117):
    directory = Path(directory)
    document, library = synthetic_design(instance_count=count, connections_per_instance=3, seed=seed)
    ports = ["input wire clk"]
    ports.extend(f"input wire [WIDTH-1:0] input_{channel}" for channel in range(3))
    ports.extend(f"output reg [WIDTH-1:0] output_{channel}" for channel in range(3))
    rtl = "module synthetic_cell #(parameter WIDTH = 8)(\n  " + ",\n  ".join(ports) + ");\n"
    rtl += "always @(posedge clk) begin\n" + "".join(f"  output_{channel} <= input_{channel};\n" for channel in range(3)) + "end\nendmodule\n"
    metadata = library[0].to_dict()
    metadata["description"] = "Registered benchmark lanes; synthetic traffic topology"
    metadata["source"]["sha256"] = hashlib.sha256(rtl.encode("utf-8")).hexdigest()
    metadata["ports"].insert(0, {"name": "clk", "dir": "in", "width": "1", "role": {"kind": "clock", "confidence": 1, "confirmed": True}})
    document["name"] = "performance_bd"
    document["ports"] = {"clk": {"direction": "input"}}
    document["nets"].insert(0, {"name": "clock_net", "endpoints": [{"ext": "clk"}, *[{"inst": instance["name"], "port": "clk"} for instance in document["instances"]]]})
    document["project_ips"] = [metadata]
    errors = [item.to_dict() for item in validate(document, (IpMetadata.from_dict(metadata),)) if item.severity == "error"]
    if errors:
        raise ValueError(errors)
    columns = math.ceil(math.sqrt(count))
    layout = {"nodes": {instance["name"]: {"x": 280 + index % columns * 360, "y": 80 + index // columns * 240}
                        for index, instance in enumerate(document["instances"])}, "viewport": {"x": 0, "y": 0, "zoom": 0.75}}
    layout["nodes"]["@clk"] = {"x": 20, "y": 80}
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "synthetic_cell.v").write_bytes(rtl.encode("utf-8"))
    (directory / "design.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    (directory / "design.layout.json").write_text(json.dumps(layout, indent=2) + "\n", encoding="utf-8")
    return document, layout


def main():
    parser = argparse.ArgumentParser(description="Generate a deterministic local GUI performance fixture")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--instances", type=int, choices=(100, 500, 2000), required=True)
    args = parser.parse_args()
    document, _ = write_fixture(args.output, args.instances)
    print(json.dumps({"instances": len(document["instances"]), "nets": len(document["nets"]), "seed": 20261117}))


if __name__ == "__main__":
    main()