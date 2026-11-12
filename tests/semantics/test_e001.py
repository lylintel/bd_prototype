import pytest
from core.semantic import validate


@pytest.mark.parametrize("width", [4, 12, 16])
def test_e001_positive(bundle, width):
    document, library = bundle
    document["instances"][0]["params"]["WIDTH"] = width
    issues = [item for item in validate(document, library) if item.code == "E001"]
    assert len(issues) == 1
    assert issues[0].location == {"instance": "compare_0", "port": "value", "net": "count_bus"}
    assert issues[0].fix["value"] == width


@pytest.mark.parametrize("width", [4, 8, 12])
def test_e001_negative(bundle, width):
    document, library = bundle
    for instance in document["instances"]:
        instance["params"]["WIDTH"] = width
    assert not any(item.code == "E001" for item in validate(document, library))