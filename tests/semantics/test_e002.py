import copy
import pytest
from core.semantic import validate


@pytest.mark.parametrize("case", ["output_output", "no_driver", "duplicate_sink"])
def test_e002_positive(bundle, case):
    document, library = bundle
    if case == "output_output":
        document["nets"][2]["endpoints"].append({"inst": "compare_0", "port": "match"})
    elif case == "no_driver":
        document["nets"][2]["endpoints"].pop(0)
    else:
        document["nets"].append({**copy.deepcopy(document["nets"][2]), "name": "another_bus"})
    assert any(item.code == "E002" for item in validate(document, library))


@pytest.mark.parametrize("width", [4, 8, 12])
def test_e002_negative(bundle, width):
    document, library = bundle
    for instance in document["instances"]:
        instance["params"]["WIDTH"] = width
    document["ports"]["count_out"] = {"direction": "output", "range": [width - 1, 0]}
    document["nets"][2]["endpoints"].append({"ext": "count_out"})
    assert not any(item.code == "E002" for item in validate(document, library))