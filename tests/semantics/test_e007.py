import copy
import pytest
from core.semantic import validate


@pytest.mark.parametrize("name", ["clk_net", "counter_0", "clk"])
def test_e007_positive(bundle, name):
    document, library = bundle
    document["nets"].append({**copy.deepcopy(document["nets"][0]), "name": name})
    assert any(item.code == "E007" for item in validate(document, library))


@pytest.mark.parametrize("name", ["net_a", "net_1", "net$"])
def test_e007_negative(bundle, name):
    document, library = bundle
    document["nets"][0]["name"] = name
    assert not any(item.code == "E007" for item in validate(document, library))