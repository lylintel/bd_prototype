import pytest
from core.semantic import validate


@pytest.mark.parametrize("net", ["clk_net", "rst_net", "match_net"])
def test_e003_positive(bundle, net):
    document, library = bundle
    document["nets"] = [item for item in document["nets"] if item["name"] != net]
    assert any(item.code == "E003" for item in validate(document, library))


@pytest.mark.parametrize("width", [4, 8, 12])
def test_e003_negative(bundle, width):
    document, library = bundle
    for instance in document["instances"]:
        instance["params"]["WIDTH"] = width
    document["ports"]["unused_input"] = {"direction": "input"}
    assert not any(item.code == "E003" for item in validate(document, library))