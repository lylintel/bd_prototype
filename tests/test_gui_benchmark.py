import json

import pytest

from bdgui import Workspace
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