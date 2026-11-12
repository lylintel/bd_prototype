import copy
import pytest
from core.semantic import validate


@pytest.mark.parametrize("case", ["counter", "compare", "new_instance"])
def test_w010_positive(bundle, case):
    document, library = bundle
    if case == "new_instance":
        document["instances"].append({**copy.deepcopy(document["instances"][0]), "name": "extra"})
    else:
        name = "count_bus" if case == "counter" else "match_net"
        document["nets"] = [net for net in document["nets"] if net["name"] != name]
    issues = [item for item in validate(document, library) if item.code == "W010"]
    assert issues and all(item.severity == "warning" for item in issues)


@pytest.mark.parametrize("width", [4, 8, 12])
def test_w010_negative(bundle, width):
    document, library = bundle
    for instance in document["instances"]:
        instance["params"]["WIDTH"] = width
    assert not any(item.code == "W010" for item in validate(document, library))