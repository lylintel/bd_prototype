from scripts.spike_pyslang import FIXTURES, capture


def test_installed_parser_matches_fixture_golden():
    assert capture() == (FIXTURES / "spike.syntax.golden.json").read_bytes()