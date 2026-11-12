import pytest
from core.semantic import validate


@pytest.mark.parametrize("section,name", [("design", "module"), ("instance", "1bad"), ("net", "bad-name")])
def test_e008_positive(bundle, section, name):
    document, library = bundle
    if section == "design":
        document["name"] = name
    elif section == "instance":
        document["instances"][0]["name"] = name
    else:
        document["nets"][0]["name"] = name
    assert any(item.code == "E008" for item in validate(document, library))


@pytest.mark.parametrize("name", ["Top_1", "_top", "top$demo"])
def test_e008_negative(bundle, name):
    document, library = bundle
    document["name"] = name
    assert not any(item.code == "E008" for item in validate(document, library))


@pytest.mark.parametrize("endpoint", [{"inst": "counter_0", "port": "assign"}, {"inst": "bad-name", "port": "count"}, {"ext": "1bad"}])
def test_e008_checks_referenced_identifiers(bundle, endpoint):
    document, library = bundle
    document["nets"][0]["endpoints"][0] = endpoint
    assert any(item.code == "E008" for item in validate(document, library))