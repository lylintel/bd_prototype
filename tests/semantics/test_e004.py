import pytest
from core.semantic import validate


@pytest.mark.parametrize("endpoint", [{"inst": "counter_0", "port": "missing"}, {"ext": "missing"}, {"inst": "missing", "port": "count"}])
def test_e004_positive(bundle, endpoint):
    document, library = bundle
    document["nets"][0]["endpoints"][0] = endpoint
    assert any(item.code == "E004" for item in validate(document, library))


@pytest.mark.parametrize("endpoint", [{"inst": "counter_0", "port": "clk"}, {"ext": "clk"}, {"inst": "counter_0", "port": "count"}])
def test_e004_negative(bundle, endpoint):
    document, library = bundle
    document["nets"][0]["endpoints"][0] = endpoint
    assert not any(item.code == "E004" for item in validate(document, library))