import copy
from dataclasses import replace
from pathlib import Path

import pytest

from bdip import IpParameter, IpRole
from core.resolve import resolve
from core.semantic import inspect_design


def test_parameter_width_and_role_are_resolved_from_new_metadata(bundle, monkeypatch):
    document, library = bundle
    library = (replace(library[0], ports=(replace(library[0].ports[0], role=IpRole("clock", 0.95, False)), *library[0].ports[1:])), library[1])
    document["instances"][0]["params"]["WIDTH"] = "4 * 3"
    before = copy.deepcopy(document)

    def no_io(*args, **kwargs):
        raise AssertionError("resolver must not read files")

    monkeypatch.setattr(Path, "open", no_io)
    resolved = resolve(document, library)
    counter = resolved.instances["counter_0"]
    assert counter.parameters["WIDTH"] == 12
    assert counter.ports["count"].width == 12
    assert counter.ports["count"].bounds == (11, 0)
    assert counter.ports["clk"].role == IpRole("clock", 0.95, False)
    assert document == before
    assert library[0].parameters[0].default == "8"


def test_dependency_defaults_follow_overrides(bundle):
    document, library = bundle
    library = (replace(library[0], parameters=(*library[0].parameters, IpParameter("TOTAL", "int", "WIDTH * 2"))), library[1])
    document["instances"][0]["params"]["WIDTH"] = 5
    assert resolve(document, library).instances["counter_0"].parameters["TOTAL"] == 10


@pytest.mark.parametrize("override", [{"WIDTH": 0}, {"WIDTH": True}, {"WIDTH": "1/0"}, {"WIDTH": "UNKNOWN"}, {"NOPE": 8}, {"WIDTH": 2**31}])
def test_bad_parameter_does_not_discard_other_instances(bundle, override):
    document, library = bundle
    document["instances"][0]["params"] = override
    resolved = resolve(document, library)
    assert "compare_0" in resolved.instances
    assert any(item.code in {"D001", "D002"} for item in resolved.diagnostics)
    assert any(item.location.get("instance") == "counter_0" for item in resolved.diagnostics)


def test_cyclic_defaults_and_inconsistent_width_are_rejected(bundle):
    document, library = bundle
    document["instances"][0]["params"] = {}
    cyclic = replace(library[0], parameters=(IpParameter("WIDTH", "int", "TOTAL"), IpParameter("TOTAL", "int", "WIDTH")))
    assert any(item.code == "D002" for item in resolve(document, (cyclic, library[1])).diagnostics)
    broken = replace(library[0], ports=(*library[0].ports[:-1], replace(library[0].ports[-1], width="99")))
    assert any(item.code == "D003" for item in resolve(document, (broken, library[1])).diagnostics)


def test_width_mismatch_updates_diagnostic_and_interfaces(bundle):
    document, library = bundle
    document["instances"][0]["params"]["WIDTH"] = 12
    result = inspect_design(document, library)
    assert not result["valid"]
    assert result["interfaces"]["instances"]["counter_0"]["count"]["width"] == 12
    mismatch = next(item for item in result["diagnostics"] if item["code"] == "E001")
    assert mismatch["params"]["source_width"] == 12
    assert mismatch["params"]["target_width"] == 8


def test_old_hdl_bytes_are_reused_without_old_validation(bundle, monkeypatch):
    document, library = bundle
    import bdtool

    def forbidden(*args, **kwargs):
        raise AssertionError("new semantics cannot use legacy validation")

    monkeypatch.setattr(bdtool, "validate_design", forbidden)
    result = inspect_design(document, library)
    assert result["valid"]
    root = Path(__file__).resolve().parents[1] / "golden/counter_compare"
    for name, text in result["files"].items():
        assert text.encode("utf-8") == (root / name).read_bytes()


@pytest.mark.parametrize("example", ["counter_compare", "uart_loopback", "builtin_counter"])
def test_semantic_service_matches_all_existing_hdl_goldens(example):
    import json
    from bdgui import Workspace

    root = Path(__file__).resolve().parents[2]
    document = json.loads((root / "examples" / f"{example}.json").read_text(encoding="utf-8"))
    result = Workspace(root, f"examples/{example}.json").semantic_inspect(document, "examples")
    assert result["valid"], result["diagnostics"]
    for name, text in result["files"].items():
        assert text.encode("utf-8") == (root / "tests/golden" / example / name).read_bytes()