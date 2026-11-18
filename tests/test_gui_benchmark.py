import json
from unittest.mock import patch

import pytest

from bdgui import Workspace
from core.design import DesignFormatError, check_document
from core.hierarchy import collapse_design
from scripts.gui_benchmark import write_fixture


@pytest.mark.parametrize("count", [100, 500, 2000])
def test_gui_benchmark_fixture_is_loadable_and_deterministic(tmp_path, count):
    document, layout = write_fixture(tmp_path, count)
    before = (tmp_path / "design.json").read_bytes()
    assert len(document["instances"]) == count
    assert len(document["nets"]) == count * 3 + 1
    assert len(layout["nodes"]) == count + 1
    loaded = Workspace(tmp_path, "design.json").load("design.json")
    assert loaded["inspection"]["valid"]
    assert loaded["design"] == json.loads(before)
    write_fixture(tmp_path, count)
    assert (tmp_path / "design.json").read_bytes() == before


def test_schema_cache_is_content_addressed_and_does_not_cache_semantics(tmp_path):
    write_fixture(tmp_path, 100)
    workspace = Workspace(tmp_path, "design.json")
    with patch("core.design.check_document", wraps=check_document) as checker:
        assert workspace.load("design.json")["inspection"]["valid"]
        assert workspace.load("design.json")["inspection"]["valid"]
        assert checker.call_count == 1
        source = tmp_path / "synthetic_cell.v"
        source.write_bytes(source.read_bytes() + b"\n")
        assert not workspace.load("design.json")["inspection"]["valid"]
        assert checker.call_count == 1
        path = tmp_path / "design.json"
        data = path.read_bytes().replace(b'"schema_version": 2', b'"schema_version": 0', 1)
        path.write_bytes(data)
        with pytest.raises(DesignFormatError):
            workspace.load("design.json")
        assert checker.call_count == 2


def test_hierarchy_workspace_roundtrip_and_generated_sources(tmp_path):
    from bdsemantic import generate_document, prepare, save_document

    document, layout = write_fixture(tmp_path, 12)
    workspace = Workspace(tmp_path, "design.json")
    prepared, library = prepare(workspace, document, ".")
    folded = collapse_design(prepared, library, ["unit_0", "unit_1"], "pair")
    inspection = workspace.semantic_inspect(folded, ".")
    assert inspection["valid"], inspection["diagnostics"]
    assert inspection["canvas"]["instances"]["pair"]["module"] == "pair"
    saved = save_document(workspace, {"design": folded, "base_dir": ".", "path": "designs/folded.json", "layout": layout})
    assert saved["inspection"]["valid"]
    assert saved["design"]["subdesigns"] == folded["subdesigns"]
    assert all(item["id"] != "pair" for item in saved["design"]["project_ips"])
    generated = generate_document(workspace, {"design": saved["design"], "base_dir": "designs"})
    assert "pair.v" in generated["files"]


def test_hierarchy_workspace_derives_interfaces_once_per_inspection(tmp_path, monkeypatch):
    import core.hierarchy as hierarchy
    import core.semantic as semantic
    from bdsemantic import prepare

    document, _ = write_fixture(tmp_path, 12)
    workspace = Workspace(tmp_path, "design.json")
    prepared, library = prepare(workspace, document, ".")
    folded = collapse_design(prepared, library, ["unit_0", "unit_1"], "pair")
    original = hierarchy.hierarchy_library
    calls = []

    def derive(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(hierarchy, "hierarchy_library", derive)
    resolver = hierarchy.resolve
    resolved = []

    def resolve_once(*args, **kwargs):
        resolved.append(args[0]["name"])
        return resolver(*args, **kwargs)

    monkeypatch.setattr(hierarchy, "resolve", resolve_once)
    monkeypatch.setattr(semantic, "resolve", resolve_once)
    assert workspace.semantic_inspect(folded, ".")["valid"]
    assert len(calls) == 1
    assert resolved.count("pair") == 1


def test_hierarchy_scoped_inspection_keeps_root_errors_and_layout(tmp_path):
    from bdgui import check_layout
    from bdsemantic import collapse_workspace, inspect_scope

    document, _ = write_fixture(tmp_path, 12)
    workspace = Workspace(tmp_path, "design.json")
    result = collapse_workspace(workspace, {"design": document, "base_dir": ".", "selection": ["unit_0"], "name": "group"})
    root = result["document"]
    root["nets"] = []
    scoped = inspect_scope(workspace, {"design": root, "base_dir": ".", "scope": "group"})
    assert not scoped["valid"]
    assert "unit_0" in scoped["canvas"]["instances"]
    layout = {"schema_version": 1, "nodes": {}, "scopes": {"group": {"nodes": {"unit_0": {"x": 10, "y": 20}}}}}
    assert check_layout(layout)["scopes"]["group"]["nodes"] == layout["scopes"]["group"]["nodes"]


def test_500_instance_fixture_collapses_into_ten_reusable_blocks(tmp_path):
    document, layout = write_fixture(tmp_path, 500, groups=10)
    assert len(document["instances"]) == 10
    assert len(document["subdesigns"]) == 10
    assert sum(len(child["instances"]) for child in document["subdesigns"].values()) == 500
    assert len(layout["nodes"]) == 11
    assert Workspace(tmp_path, "design.json").load("design.json")["inspection"]["valid"]