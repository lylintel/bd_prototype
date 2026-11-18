import json
from unittest.mock import patch

import pytest

from bdgui import Workspace
from core.design import DesignFormatError, check_document
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