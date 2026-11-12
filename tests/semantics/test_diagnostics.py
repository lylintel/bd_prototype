import copy
import json
from pathlib import Path
from dataclasses import replace
import pytest
from core.semantic import validate, apply_fix, inspect_design


def test_diagnostic_contract_and_pure_idempotent_validation(bundle):
    document, library = bundle
    document["instances"][0]["params"]["WIDTH"] = 12
    original = copy.deepcopy(document)
    first = validate(document, library)
    assert first == validate(document, library)
    assert document == original
    for item in first:
        assert {"code", "severity", "location", "message", "params"} <= item.to_dict().keys()


def test_fix_is_explicit_pure_and_revalidated(bundle):
    document, library = bundle
    document["instances"][0]["params"]["WIDTH"] = 12
    diagnostic = next(item for item in validate(document, library) if item.code == "E001")
    candidate = apply_fix(document, library, diagnostic.to_dict())
    assert candidate["instances"][1]["params"]["WIDTH"] == 12
    assert document["instances"][1]["params"]["WIDTH"] == 8
    assert inspect_design(candidate, library)["valid"]
    with pytest.raises(ValueError):
        apply_fix(candidate, library, diagnostic.to_dict())
    forged = diagnostic.to_dict()
    forged["fix"]["value"] = 999
    with pytest.raises(ValueError):
        apply_fix(document, library, forged)


def test_warning_does_not_prevent_generation(bundle):
    document, library = bundle
    document["instances"].pop()
    document["ports"].pop("match")
    document["nets"] = document["nets"][:2]
    result = inspect_design(document, library)
    assert result["valid"]
    assert any(item["code"] == "W010" for item in result["diagnostics"])
    assert result["files"]


@pytest.mark.parametrize("diagnostic", [None, "set_param", [], {"fix": {"op": "delete_instance"}}])
def test_arbitrary_fix_payload_is_rejected(bundle, diagnostic):
    document, library = bundle
    document["instances"][0]["params"]["WIDTH"] = 12
    with pytest.raises(ValueError):
        apply_fix(document, library, diagnostic)


@pytest.mark.parametrize("value", [None, {}, "metadata"])
def test_malformed_project_metadata_container_is_a_diagnostic(bundle, value):
    document, library = bundle
    document["project_ips"] = value
    assert any(item.code == "D001" for item in validate(document, library))


def test_structured_diagnostic_bytes_match_new_golden(bundle):
    document, library = bundle
    document["instances"][0]["params"]["WIDTH"] = 12
    encoded = (json.dumps([item.to_dict() for item in validate(document, library)], ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    assert encoded == (Path(__file__).resolve().parents[1] / "fixtures/semantic/diagnostic.golden.json").read_bytes()


def test_two_versions_of_one_hdl_module_are_not_silently_linked(bundle):
    document, library = bundle
    library = (*library, replace(library[0], version="2.0.0"))
    document["instances"].append({"name": "counter_new", "ip": {"id": "counter", "version": "2.0.0"}})
    assert any(item.code == "E005" and item.params["reason"] == "hdl_version_conflict" for item in validate(document, library))