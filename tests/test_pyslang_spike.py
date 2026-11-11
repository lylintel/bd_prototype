import pytest

from scripts.spike_pyslang import BACKENDS, FIXTURES, capture_pyslang, capture_yosys


@pytest.mark.parametrize("backend", BACKENDS)
def test_installed_parser_matches_fixture_golden(backend):
    actual = capture_pyslang() if backend == "pyslang" else capture_yosys()
    golden = "spike.syntax.golden.json" if backend == "pyslang" else "spike.yosys.golden.json"
    assert actual == (FIXTURES / golden).read_bytes()