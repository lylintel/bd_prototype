from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from core.design import DesignFormatError, check_document, migrate
from core.hierarchy import collapse_design
from core.ops import apply_ops
from core.semantic import inspect_design, validate


ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).parent / "golden" / "hierarchy"


def test_hierarchy_format_cache_does_not_cache_semantics(bundle, monkeypatch):
    import core.hierarchy as hierarchy

    document, library = bundle
    folded = collapse_design(document, library, [document["instances"][0]["name"]], "cache_group")
    folded["name"] = "cache_probe"
    checked = []
    original = hierarchy.check_document

    def checker(value):
        checked.append(True)
        original(value)

    monkeypatch.setattr(hierarchy, "check_document", checker)
    assert inspect_design(folded, library)["valid"]
    assert inspect_design(folded, library)["valid"]
    assert len(checked) == 1
    folded["subdesigns"]["cache_group"]["nets"] = []
    assert not inspect_design(folded, library)["valid"]
    assert len(checked) == 2


def test_collapse_preserves_source_and_emits_separate_module(bundle):
    document, library = bundle
    before = deepcopy(document)
    selected = [document["instances"][0]["name"]]
    result = collapse_design(document, library, selected, "counter_group")
    assert document == before
    assert result["schema_version"] == 4
    check_document(result)
    child = result["subdesigns"]["counter_group"]
    assert [item["name"] for item in child["instances"]] == selected
    assert len(result["instances"]) == len(document["instances"])
    assert {port["direction"] for port in child["ports"].values()} == {"input", "output"}
    inspection = inspect_design(result, library)
    assert inspection["valid"], inspection["diagnostics"]
    assert "counter_group.v" in inspection["files"]
    assert "counter_group_wrapper.v" not in inspection["files"]
    assert "counter_group counter_group" in inspection["files"][f"{document['name']}.v"]


def test_v4_migration_keeps_old_golden_bytes(bundle):
    document, library = bundle
    upgraded = migrate(document, library, target_version=4)
    assert upgraded["subdesigns"] == {}
    assert inspect_design(upgraded, library)["files"] == inspect_design(document, library)["files"]
    with pytest.raises(DesignFormatError):
        migrate(upgraded, library, target_version=3)


@pytest.mark.parametrize("selection,name", [([], "group"), (["missing"], "group"), (["counter0"], "module"), (["counter0"], "../escape")])
def test_collapse_rejects_bad_selection_or_identifier(bundle, selection, name):
    document, library = bundle
    with pytest.raises(DesignFormatError):
        collapse_design(document, library, selection, name)


def test_child_errors_block_parent_generation_with_location(bundle):
    document, library = bundle
    result = collapse_design(document, library, [document["instances"][0]["name"]], "counter_group")
    result["subdesigns"]["counter_group"]["nets"] = []
    inspection = inspect_design(result, library)
    assert not inspection["valid"]
    assert inspection["files"] == {}
    assert any(item["location"].get("design") == "counter_group" for item in inspection["diagnostics"])
    assert any(item.severity == "error" for item in validate(result, library))


def test_hierarchy_cycle_and_library_collision_are_rejected(bundle):
    document, library = bundle
    result = collapse_design(document, library, [document["instances"][0]["name"]], "counter_group")
    result["subdesigns"]["counter_group"]["instances"].append({"name": "recursive", "ip": {"id": "counter_group", "version": "1.0.0"}})
    inspection = inspect_design(result, library)
    assert not inspection["valid"]
    assert inspection["files"] == {}
    with pytest.raises(DesignFormatError):
        collapse_design(document, library, [document["instances"][0]["name"]], library[0].id)


def test_nested_hierarchy_generates_each_definition_once(bundle):
    document, library = bundle
    first = collapse_design(document, library, ["counter_0"], "counter_group")
    nested = collapse_design(first, library, ["counter_group", "compare_0"], "outer_group")
    inspection = inspect_design(nested, library)
    assert inspection["valid"], inspection["diagnostics"]
    assert len(nested["instances"]) == 1
    assert {"counter_group.v", "outer_group.v"} <= inspection["files"].keys()
    assert len(inspection["files"]) == 4


def test_mixed_concat_boundary_is_explicitly_rejected_without_mutation(bundle):
    document, library = bundle
    document["schema_version"] = 3
    document["ports"]["extra_data"] = {"direction": "input", "range": [7, 0]}
    document["instances"][1]["params"]["WIDTH"] = 16
    net = next(item for item in document["nets"] if item["name"] == "count_bus")
    net["endpoints"] = [{"concat": [{"inst": "counter_0", "port": "count"}, {"ext": "extra_data"}]}, {"inst": "compare_0", "port": "value"}]
    assert inspect_design(document, library)["valid"]
    before = deepcopy(document)
    with pytest.raises(DesignFormatError) as caught:
        collapse_design(document, library, ["counter_0"], "counter_group")
    assert caught.value.diagnostic.params["reason"] == "hierarchy_mixed_concat"
    assert document == before


def test_hierarchy_reuses_typed_operations_and_rejects_unwired_clone(bundle):
    document, library = bundle
    folded = collapse_design(document, library, [document["instances"][0]["name"]], "counter_group")
    result, errors = apply_ops(folded, library, [{"op": "add_instance", "name": "second_group", "ip": "counter_group", "version": "1.0.0"}])
    assert any(item.code == "E003" for item in errors)
    assert len(result["instances"]) == len(folded["instances"]) + 1


def test_hierarchy_example_matches_golden_and_verilator(tmp_path):
    from bdip import IpMetadata

    document = json.loads((ROOT / "examples" / "hierarchy" / "counter.json").read_text(encoding="utf-8"))
    library = tuple(IpMetadata.from_dict(item) for item in document["project_ips"])
    result = inspect_design(document, library)
    assert result["valid"], result["diagnostics"]
    assert set(result["files"]) == {item.name for item in GOLDEN.glob("*.v")}
    for name, text in result["files"].items():
        assert text.encode("utf-8") == (GOLDEN / name).read_bytes()
        (tmp_path / name).write_bytes(text.encode("utf-8"))
    executable = os.environ.get("BD_VERILATOR") or shutil.which("verilator") or shutil.which("verilator_bin")
    assert executable, "Install Verilator or set BD_VERILATOR to its executable"
    sources = sorted({str(ROOT / "examples" / "hierarchy" / item.source.path) for item in library})
    lint = subprocess.run([executable, "--lint-only", "--top-module", f"{document['name']}_wrapper",
                           *sources, *[str(tmp_path / name) for name in result["files"]]],
                          capture_output=True, text=True, timeout=30, cwd=tmp_path)
    assert lint.returncode == 0, lint.stdout + lint.stderr


if __name__ == "__main__":
    from bdip import migrate_legacy_modules

    if sys.argv[1:] != ["--update"]:
        raise SystemExit("Use --update to regenerate only the hierarchy example and goldens")
    original = json.loads((ROOT / "examples" / "counter_compare.json").read_text(encoding="utf-8"))
    library = tuple(migrate_legacy_modules(original, ROOT / "examples", workspace_root=ROOT).values())
    migrated = migrate(original, library)
    for instance in migrated["instances"]:
        instance["params"]["WIDTH"] = 32
    document = collapse_design(migrated, library, list(original["instances"]), "counter_group")
    GOLDEN.mkdir(parents=True, exist_ok=True)
    for name, text in inspect_design(document, library)["files"].items():
        (GOLDEN / name).write_bytes(text.encode("utf-8"))
    for metadata in document["project_ips"]:
        metadata["source"]["path"] = "../" + metadata["source"]["path"]
    destination = ROOT / "examples" / "hierarchy" / "counter.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes((json.dumps(document, indent=2) + "\n").encode("utf-8"))