import json
from pathlib import Path
import shutil
import subprocess

import pytest

from bdip import load_ip
from core.design import DesignFormatError, check_document, migrate
from core.semantic import inspect_design, validate


@pytest.mark.parametrize("kind", ["slice", "constant", "concat", "partial_sink", "concat_sink"])
def test_connection_expressions_compile_with_icarus(bundle, tmp_path, kind):
    document, library = bundle
    document = migrate(document, library, target_version=3)
    source = {"inst": "counter_0", "port": "count"}
    target = {"inst": "compare_0", "port": "value"}
    if kind == "slice":
        document["instances"][1]["params"]["WIDTH"] = 4
        document["nets"][2]["endpoints"][0] = {**source, "slice": [7, 4]}
    elif kind == "constant":
        document["nets"][2]["endpoints"][0] = {"const": "8'd5"}
    elif kind == "concat":
        document["nets"][2]["endpoints"][0] = {"concat": [{**source, "slice": [3, 0]}, {"const": "4'b0000"}]}
    elif kind == "partial_sink":
        document["nets"][2]["endpoints"] = [{**source, "slice": [3, 0]}, {**target, "slice": [3, 0]}]
        document["nets"].append({"name": "upper", "endpoints": [{**source, "slice": [7, 4]}, {**target, "slice": [7, 4]}]})
    else:
        document["nets"][2]["endpoints"][1] = {"concat": [{**target, "slice": [3, 0]}, {**target, "slice": [7, 4]}]}
    check_document(document)
    result = inspect_design(document, library)
    assert result["valid"], result["diagnostics"]
    paths = []
    for name, text in result["files"].items():
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        paths.append(str(path))
    root = Path(__file__).resolve().parents[2]
    command = [shutil.which("iverilog"), "-g2005", "-s", "example_bd_wrapper", "-o", str(tmp_path / "sim"),
               str(root / "examples/rtl/counter.v"), str(root / "examples/rtl/compare_eq.v"), *paths]
    compiled = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stderr
    assert "warning" not in compiled.stderr.lower()


@pytest.mark.parametrize("bounds", [[-1, 0], [8, 0], [0, 3], [True, 0], ["7", 0], [3], [3, 0, 0]])
def test_slice_bounds_are_checked(bundle, bounds):
    document, library = bundle
    document = migrate(document, library, target_version=3)
    document["nets"][2]["endpoints"][0]["slice"] = bounds
    assert any(item.code == "D007" for item in validate(document, library))


@pytest.mark.parametrize("literal", ["5", "'h5", "8'dx", "8'd1;endmodule", "0'd0", "4096'd0"])
def test_constants_require_safe_explicit_width(bundle, literal):
    document, library = bundle
    document = migrate(document, library, target_version=3)
    document["nets"][2]["endpoints"][0] = {"const": literal}
    result = inspect_design(document, library)
    assert not result["valid"]
    assert any(item["code"] == "D007" for item in result["diagnostics"])
    assert not result["files"]


def test_concat_rejects_mixed_direction_and_excessive_depth(bundle):
    document, library = bundle
    document = migrate(document, library, target_version=3)
    document["nets"][2]["endpoints"][0] = {"concat": [{"inst": "counter_0", "port": "count"}, {"inst": "compare_0", "port": "value"}]}
    assert any(item.code == "D007" for item in validate(document, library))
    nested = {"const": "8'd0"}
    for _ in range(20):
        nested = {"concat": [nested]}
    document["nets"][2]["endpoints"][0] = nested
    assert any(item.code == "D007" for item in validate(document, library))


def test_partial_input_requires_full_coverage_and_no_overlapping_drivers(bundle):
    document, library = bundle
    document = migrate(document, library, target_version=3)
    target = {"inst": "compare_0", "port": "value", "slice": [3, 0]}
    document["nets"][2]["endpoints"] = [{"const": "4'd1"}, target]
    assert any(item.code == "E003" and item.location.get("port") == "value" for item in validate(document, library))
    document["nets"].append({"name": "overlap", "endpoints": [{"const": "4'd2"}, target]})
    assert any(item.code == "E002" for item in validate(document, library))


def test_version_migration_and_unused_features_keep_old_hdl(bundle):
    document, library = bundle
    original = inspect_design(document, library)["files"]
    upgraded = migrate(document, library, target_version=3)
    assert upgraded["schema_version"] == 3
    assert document["schema_version"] == 2
    assert inspect_design(upgraded, library)["files"] == original
    document["nets"][2]["endpoints"][0]["slice"] = [7, 0]
    with pytest.raises(DesignFormatError):
        check_document(document)
    assert any(item.code == "D007" for item in validate(document, library))
    with pytest.raises(DesignFormatError):
        migrate(upgraded, library, target_version=2)


def test_published_connections_golden_and_simulation(tmp_path):
    root = Path(__file__).resolve().parents[2]
    directory = root / "examples/semantic"
    document = json.loads((directory / "connections.json").read_text(encoding="utf-8"))
    metadata = load_ip(root / "ip_library/builtin/bd_mux2/1.0.0/ip.json")
    check_document(document)
    result = inspect_design(document, (metadata,))
    assert result["valid"], result["diagnostics"]
    captured = {key: result[key] for key in ("valid", "diagnostics", "files")}
    golden = root / "tests/fixtures/semantic/connections.golden.json"
    assert (json.dumps(captured, indent=2, ensure_ascii=False) + "\n").encode() == golden.read_bytes()
    sources = []
    for name, text in result["files"].items():
        destination = tmp_path / name
        destination.write_bytes(text.encode())
        sources.append(str(destination))
    executable = tmp_path / "simulation"
    compiled = subprocess.run([shutil.which("iverilog"), "-g2012", "-s", "tb", "-o", str(executable), *sources,
                               str(root / "ip_library/builtin/bd_mux2/1.0.0/src/bd_mux2.v"), str(directory / "connections_tb.sv")],
                              capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0 and "warning:" not in compiled.stderr.lower(), compiled.stderr
    simulated = subprocess.run([shutil.which("vvp"), str(executable)], capture_output=True, text=True, timeout=15)
    assert simulated.returncode == 0 and "PASS connections_bd" in simulated.stdout, simulated.stdout + simulated.stderr