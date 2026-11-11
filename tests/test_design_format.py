import copy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from bdip import migrate_legacy_modules
from core.design import DesignFormatError, load_document, migrate, check_document


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def legacy_bundle():
    original = json.loads((ROOT / "examples/counter_compare.json").read_text(encoding="utf-8"))
    library = tuple(migrate_legacy_modules(original, ROOT / "examples", workspace_root=ROOT).values())
    return original, library


def test_migration_is_explicit_lossless_and_immutable(legacy_bundle):
    original, library = legacy_bundle
    before = copy.deepcopy(original)
    migrated = migrate(original, library)
    assert migrated["schema_version"] == 2
    assert migrated["instances"][0] == {"name": "counter_0", "ip": {"id": "counter", "version": "1.0.0"}, "params": {"WIDTH": 8}}
    assert migrated["nets"][0] == {"name": "clk_net", "endpoints": [{"ext": "clk"}, {"inst": "counter_0", "port": "clk"}]}
    assert migrated["ports"] == original["ports"]
    assert original == before
    assert migrate(migrated, library) == migrated
    assert migrate(migrated, library) is not migrated
    check_document(migrated)


@pytest.mark.parametrize("mode", ["absent", "versions", "duplicate"])
def test_legacy_ip_reference_never_guesses(legacy_bundle, mode):
    original, library = legacy_bundle
    choices = () if mode == "absent" else (*library, replace(library[0], version="2.0.0") if mode == "versions" else library[0])
    with pytest.raises(DesignFormatError) as raised:
        migrate(original, choices)
    issue = raised.value.diagnostic.to_dict()
    assert issue["code"] == "E005"
    assert issue["location"]["instance"] == "counter_0"
    assert issue["params"]["reason"] == ("missing" if mode == "absent" else "ambiguous")
    assert issue["message"]


@pytest.mark.parametrize("field,value", [("schema_version", 3), ("schema_version", True), ("instances", {}), ("nets", {}), ("unknown", 1)])
def test_versioned_structure_rejects_invalid_fields(legacy_bundle, field, value):
    original, library = legacy_bundle
    document = migrate(original, library)
    document[field] = value
    with pytest.raises(DesignFormatError):
        check_document(document)


@pytest.mark.parametrize("text", ['{"schema_version":2,"schema_version":2}', '{"value":NaN}', '[]', '{'])
def test_reader_rejects_duplicate_nonfinite_or_invalid_json(text):
    with pytest.raises(DesignFormatError):
        load_document(text)


def test_reader_rejects_oversized_document():
    with pytest.raises(DesignFormatError):
        load_document(" " * (2 * 1024 * 1024 + 1))


def test_empty_canvas_keeps_project_catalog(legacy_bundle):
    original, library = legacy_bundle
    original.update(instances={}, nets={}, ports={})
    assert len(migrate(original, library)["project_ips"]) == 2


def test_same_name_incompatible_metadata_is_not_a_migration(legacy_bundle):
    original, library = legacy_bundle
    original["modules"]["counter"]["ports"]["count"]["range"] = [3, 0]
    with pytest.raises(DesignFormatError) as raised:
        migrate(original, library)
    assert raised.value.diagnostic.code == "E005"
    assert raised.value.diagnostic.params["reason"] == "definition_conflict"