import copy
import pytest
from core.semantic import validate


@pytest.mark.parametrize("name", ["counter_0", "compare_0", "clk"])
def test_e006_positive(bundle, name):
    document, library = bundle
    document["instances"].append({**copy.deepcopy(document["instances"][0]), "name": name})
    assert any(item.code == "E006" for item in validate(document, library))


@pytest.mark.parametrize("name", ["counter_1", "counter$", "counter_long"])
def test_e006_negative(bundle, name):
    document, library = bundle
    document["instances"][0]["name"] = name
    assert not any(item.code == "E006" for item in validate(document, library))