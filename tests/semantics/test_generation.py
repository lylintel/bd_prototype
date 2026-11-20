from copy import deepcopy
import json

import pytest

from core.design import DesignFormatError
from core.generation import generate_files
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