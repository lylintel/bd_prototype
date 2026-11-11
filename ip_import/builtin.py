from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import tempfile

import bdtool
from bdip import MESSAGES
from .library import IpLibrary, LibraryError, Upload, _version


ROOT = Path(__file__).resolve().parents[1]


def _encode(data: object) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _external_port(port: bdtool.Port, direction: str | None = None) -> dict:
    result = {"direction": direction or port.direction, "signed": port.signed}
    if port.bounds is not None:
        result["range"] = list(port.bounds)
    return result


def _standalone(name: str, definition: dict) -> dict:
    values = bdtool._parameters(definition["parameters"], {}, name)
    ports = bdtool._ports(definition["ports"], values, name)
    return {"name": f"{name}_bd", "modules": {name: definition},
            "ports": {port_name: _external_port(port) for port_name, port in ports.items()},
            "instances": {"dut": {"module": name, "parameters": {}}},
            "nets": {f"{port_name}_net": [f"@{port_name}", f"dut.{port_name}"] for port_name in ports}}


def _counter_example(definitions: dict[str, dict]) -> dict:
    counter = definitions["bd_counter"]
    values = bdtool._parameters(counter["parameters"], {}, "bd_counter")
    ports = bdtool._ports(counter["ports"], values, "bd_counter")
    external = {name: _external_port(ports[name]) for name in ("clk", "rst", "enable", "clear", "count", "overflow")}
    external["threshold"] = _external_port(ports["count"], "input")
    external.update({name: {"direction": "output"} for name in ("equal", "less", "greater")})
    nets = {f"{name}_net": [f"@{name}", f"counter_0.{name}"] for name in ("clk", "rst", "enable", "clear")}
    nets.update({"count_bus": ["counter_0.count", "compare_0.left_data", "@count"],
                 "threshold_bus": ["@threshold", "compare_0.right_data"], "overflow_net": ["counter_0.overflow", "@overflow"]})
    nets.update({f"{name}_net": [f"compare_0.{name}", f"@{name}"] for name in ("equal", "less", "greater")})
    return {"name": "builtin_counter_bd", "modules": {"bd_counter": counter, "bd_compare": definitions["bd_compare"]},
            "ports": external, "instances": {"counter_0": {"module": "bd_counter", "parameters": {}},
            "compare_0": {"module": "bd_compare", "parameters": {"WIDTH": values["WIDTH"]}}}, "nets": nets}


def capture_bundle(root: Path = ROOT) -> dict[str, bytes]:
    root = Path(root).resolve()
    directory = root / "ip_library" / "builtin"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("origin") != "original":
        raise LibraryError("IP_BUILTIN_MANIFEST")
    outputs = {}
    with tempfile.TemporaryDirectory(prefix="bd-builtin-") as temporary:
        workspace = Path(temporary)
        library = IpLibrary(workspace)
        for profile in manifest["entries"]:
            name = bdtool._name(profile["id"], "builtin.id")
            _version(profile["version"])
            source = directory / name / profile["version"] / "src" / f"{name}.v"
            if not source.resolve().is_relative_to(directory):
                raise LibraryError("IP_LIBRARY_PATH")
            upload = Upload(source.name, source.read_bytes())
            preview = [event for event in library.import_sources([upload], dry_run=True, license_name=manifest["license"], origin="builtin")
                       if event["type"] == "ip"]
            if len(preview) != 1 or preview[0].get("id") != name or "metadata" not in preview[0]:
                raise LibraryError("IP_BUILTIN_MANIFEST", name)
            metadata = preview[0]["metadata"]
            metadata.update(version=profile["version"], display_name=profile["display_name"], description=profile["description"], tags=profile["tags"])
            if set(profile["parameters"]) != {parameter["name"] for parameter in metadata["parameters"]}:
                raise LibraryError("IP_BUILTIN_MANIFEST", name)
            for parameter in metadata["parameters"]:
                parameter.update(profile["parameters"][parameter["name"]])
            for port in metadata["ports"]:
                if port["name"] in profile.get("roles", {}):
                    port["role"] = profile["roles"][port["name"]]
            events = list(library.import_sources([upload], selections={name: metadata}, license_name=manifest["license"], origin="builtin"))
            if events[-1]["counts"]["imported"] != 1:
                raise LibraryError("IP_BUILTIN_MANIFEST", name)
        index = library._index(include_builtin=False)
        definitions, hdl = {}, {}
        for row in library.entries():
            name = row["metadata"]["id"]
            if not row["usable"]:
                raise LibraryError("IP_BUILTIN_MANIFEST", name)
            definition = copy.deepcopy(row["definition"])
            definition["sources"] = [f"../ip_library/builtin/{Path(source).relative_to('ip_library').as_posix()}" for source in definition["sources"]]
            definitions[name] = definition
            design = bdtool.validate_design(_standalone(name, definition), root / "examples")
            hdl[name] = {"wrapper": design.wrapper_name, "sources": [source.relative_to(root).as_posix() for source in design.sources],
                         "files": bdtool.render_verilog(design)}
        for entry in index["entries"].values():
            relative = entry["metadata"]
            outputs[f"ip_library/builtin/{relative}"] = (workspace / "ip_library" / relative).read_bytes()
            entry["metadata"] = f"builtin/{relative}"
        for source in index["sources"].values():
            source["path"] = f"builtin/{source['path']}"
        outputs["ip_library/builtin/index.json"] = (json.dumps(index, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        outputs["tests/fixtures/builtin-hdl.golden.json"] = _encode(hdl)
        example = _counter_example(definitions)
        bdtool.validate_design(example, root / "examples")
        outputs["examples/builtin_counter.json"] = _encode(example)
    return outputs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=MESSAGES["IP_BUILTIN_DESCRIPTION"])
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args(argv)
    outputs = capture_bundle()
    if args.update:
        previous_path = ROOT / "ip_library/builtin/index.json"
        if previous_path.exists():
            previous = json.loads(previous_path.read_text(encoding="utf-8"))
            current = json.loads(outputs["ip_library/builtin/index.json"])
            for entry in current["entries"].values():
                older = [item for item in previous["entries"].values() if item["id"] == entry["id"]]
                if older:
                    latest = max(older, key=lambda item: _version(item["version"]))
                    changed = (entry["source_sha256"], entry["interface_hash"]) != (latest["source_sha256"], latest["interface_hash"])
                    if changed and _version(entry["version"]) <= _version(latest["version"]):
                        raise LibraryError("IP_LIBRARY_VERSION", entry["id"])
        for relative, content in outputs.items():
            path = ROOT / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    else:
        for relative, content in outputs.items():
            if (ROOT / relative).read_bytes() != content:
                raise LibraryError("IP_BUILTIN_MANIFEST", relative)
    print(json.dumps({"status": "updated" if args.update else "checked", "files": len(outputs)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())