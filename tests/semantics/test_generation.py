from copy import deepcopy
import json
from pathlib import Path
import shutil

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