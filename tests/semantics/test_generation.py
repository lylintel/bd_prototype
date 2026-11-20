from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from core.design import DesignFormatError
from core.generation import generate_artifacts, generate_files
from core.semantic import inspect_design


def test_engineered_outputs_have_versioned_readonly_header(bundle):
    document, library = bundle
    ordered = json.loads(json.dumps(document, sort_keys=True))
    for section in ("instances", "nets"):
        ordered[section].sort(key=lambda item: item["name"])
    legacy = inspect_design(ordered, library)["files"]
    result = generate_files(document, library)
    assert list(result) == sorted(result)
    assert set(result) == set(legacy)
    for name, text in result.items():
        assert text.startswith("// AUTO-GENERATED - DO NOT EDIT\n")
        assert "schema_version: 2" in text.splitlines()[1]
        assert text.endswith(legacy[name])


def test_engineered_output_order_is_independent_of_input_insertion_order(bundle):
    document, library = bundle
    before = deepcopy(document)
    shuffled = deepcopy(document)
    shuffled["instances"].reverse()
    shuffled["nets"].reverse()
    shuffled["ports"] = dict(reversed(list(shuffled["ports"].items())))
    shuffled["project_ips"].reverse()
    assert generate_files(document, library) == generate_files(shuffled, tuple(reversed(library)))
    assert document == before


def test_engineered_generation_refuses_semantic_errors(bundle):
    document, library = bundle
    document["instances"][0]["params"]["WIDTH"] = 16
    with pytest.raises(DesignFormatError) as caught:
        generate_files(document, library)
    assert caught.value.diagnostic.severity == "error"


def test_source_map_covers_generated_instances_and_nets(bundle):
    document, library = bundle
    result = generate_artifacts(document, library)
    records = result["source_map"]["files"]["example_bd.v"]["ranges"]
    lines = result["files"]["example_bd.v"].splitlines()
    for instance in document["instances"]:
        entry = next(item for item in records if item["location"].get("instance") == instance["name"])
        block = "\n".join(lines[entry["start_line"] - 1:entry["end_line"]])
        assert instance["name"] in block and instance["ip"]["id"] in block
    assert {net["name"] for net in document["nets"]} <= {item["location"].get("net") for item in records}


def test_real_tool_warning_maps_to_generated_instance(bundle, tmp_path):
    from bdgui import Workspace
    from bdsemantic import check_generated

    document, _ = bundle
    document["schema_version"] = 3
    net = next(item for item in document["nets"] if item["name"] == "count_bus")
    net["endpoints"] = [{"const": "8'd9"}, {"inst": "compare_0", "port": "value"}]
    root = Path(__file__).resolve().parents[2]
    shutil.copytree(root / "examples/rtl", tmp_path / "rtl")
    before = deepcopy(document)
    result = check_generated(Workspace(tmp_path, "unused.json"), {"design": document, "base_dir": "."})
    warnings = [item for item in result["diagnostics"] if item["params"].get("rule") == "PINCONNECTEMPTY"]
    assert warnings and warnings[0]["location"]["instance"] == "counter_0"
    assert warnings[0]["location"]["file"] == "example_bd.v"
    assert document == before and not (tmp_path / "build").exists()


def sv_document():
    return {"schema_version": 2, "name": "sv_demo", "ports": {
        "clk": {"direction": "input"}, "data": {"direction": "input", "range": [7, 0]},
        "result": {"direction": "output", "range": [7, 0]}},
        "instances": [{"name": "register_0", "ip": {"id": "sv_register", "version": "1.0.0"}, "params": {"WIDTH": 8}}],
        "nets": [{"name": f"{name}_net", "endpoints": [{"ext": name}, {"inst": "register_0", "port": name}]} for name in ("clk", "data", "result")]}


def test_sv_generation_is_explicit_and_keeps_verilog_unchanged(bundle):
    document, library = bundle
    before = generate_files(document, library)
    result = generate_artifacts(document, library, language="sv")
    assert set(result["files"]) == {"example_bd.sv", "example_bd_wrapper.sv"}
    assert "input logic clk" in result["files"]["example_bd.sv"]
    assert "wire " not in result["files"]["example_bd.sv"]
    assert all(".*" not in text for text in result["files"].values())
    assert generate_files(document, library) == before
    with pytest.raises(ValueError):
        generate_files(document, library, language="vhdl")


def test_sv_ip_import_connect_generate_lint_and_cli(tmp_path):
    from bdgui import Workspace
    from bdsemantic import check_generated
    from ip_import.library import IpLibrary, Upload

    root = Path(__file__).resolve().parents[2]
    source = root / "examples/sv/rtl/sv_register.sv"
    events = list(IpLibrary(tmp_path).import_sources([Upload(source.name, source.read_bytes())]))
    assert events[-1]["counts"]["imported"] == 1
    metadata = IpLibrary(tmp_path).metadata_snapshot(None, base_dir=tmp_path)[0]
    assert metadata.language == "systemverilog"
    assert metadata.parameters[0].name == "WIDTH" and metadata.parameters[0].type == "int"
    document = sv_document()
    workspace = Workspace(tmp_path, "design.json")
    result = check_generated(workspace, {"design": document, "base_dir": ".", "lang": "sv"})
    assert result["valid"], result["diagnostics"]
    assert "sv_demo.sv" in result["files"] and "input logic" in result["files"]["sv_demo.sv"]
    (tmp_path / "design.json").write_text(json.dumps(document), encoding="utf-8")
    command = subprocess.run([sys.executable, "-m", "bdstudio", "generate", "design.json", "--workspace", str(tmp_path), "--lang", "sv"],
                             cwd=root, capture_output=True, encoding="utf-8", timeout=30)
    assert command.returncode == 0, command.stdout + command.stderr
    assert (tmp_path / "build/gui/sv_demo.sv").read_text(encoding="utf-8") == result["files"]["sv_demo.sv"]


if __name__ == "__main__":
    from ip_import.parser import parse_file

    if sys.argv[1:] != ["--write-sv-example"]:
        raise SystemExit("Use --write-sv-example to regenerate the SV example only")
    root = Path(__file__).resolve().parents[2]
    source = root / "examples/sv/rtl/sv_register.sv"
    parsed = parse_file(source)
    assert len(parsed.modules) == 1 and not any(item.severity == "error" for item in parsed.diagnostics)
    metadata = parsed.modules[0].to_dict()
    metadata["source"]["path"] = "rtl/sv_register.sv"
    document = {**sv_document(), "project_ips": [metadata]}
    (root / "examples/sv/register.json").write_bytes((json.dumps(document, indent=2) + "\n").encode("utf-8"))