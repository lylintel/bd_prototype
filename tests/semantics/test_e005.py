from dataclasses import replace
import pytest
from core.semantic import validate


@pytest.mark.parametrize("case", ["missing_id", "missing_version", "ambiguous"])
def test_e005_positive(bundle, case):
    document, library = bundle
    if case == "missing_id":
        document["instances"][0]["ip"]["id"] = "missing"
    elif case == "missing_version":
        document["instances"][0]["ip"]["version"] = "9.0.0"
    else:
        library = (*library, library[0])
    assert any(item.code == "E005" for item in validate(document, library))


@pytest.mark.parametrize("version", ["1.0.0", "1.1.0", "2.0.0"])
def test_e005_negative(bundle, version):
    document, library = bundle
    document["instances"][0]["ip"]["version"] = version
    library = (replace(library[0], version=version), library[1])
    assert not any(item.code == "E005" for item in validate(document, library))