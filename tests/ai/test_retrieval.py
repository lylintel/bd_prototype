from dataclasses import replace
import json
from pathlib import Path
from time import perf_counter

import pytest
import yaml

from ai.retrieval import SearchIndex
from bdip import load_ip, migrate_legacy_modules


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def catalog():
    bundled = [load_ip(path) for path in sorted((ROOT / "ip_library/builtin").glob("*/1.0.0/ip.json"))]
    legacy = json.loads((ROOT / "examples/counter_compare.json").read_text(encoding="utf-8"))
    return (*bundled, *migrate_legacy_modules(legacy, ROOT / "examples", workspace_root=ROOT).values())


def test_eval_query_top8_hits_at_least_ninety_percent(catalog):
    cases = yaml.safe_load((ROOT / "tests/ai_eval/cases.yaml").read_text(encoding="utf-8"))["cases"]
    assert len(cases) == 20
    assert sum("expression" in case for case in cases) == 3
    index = SearchIndex(catalog)
    eligible = [case for case in cases if case["expect"]["ips"]]
    missed = []
    for case in eligible:
        found = {item["id"] for item in index.search_ip(case["prompt"], k=8)}
        if not set(case["expect"]["ips"]) <= found:
            missed.append(case["id"])
    assert (len(eligible) - len(missed)) / len(eligible) >= 0.9, missed


def test_cards_are_metadata_only_and_versions_are_explicit(catalog):
    index = SearchIndex(catalog)
    cards = index.search_ip("bd_uart_rx 接收 UART", k=3)
    assert cards[0]["id"] == "bd_uart_rx"
    assert all(set(card) == {"id", "version", "parameters", "ports"} for card in cards)
    assert "source" not in json.dumps(cards) and "description" not in json.dumps(cards)
    assert index.search_ip("zzzz_unavailable_name") == []
    assert SearchIndex(()).search_ip("counter") == []


def test_search_uses_description_tags_ports_and_preserves_inputs(catalog):
    entry = replace(catalog[0], id="unique_unit", description="needle_description", tags=("needle_tag",))
    before = entry.to_dict()
    index = SearchIndex((entry,))
    for query in ("unique_unit", "needle_description", "needle_tag", entry.ports[0].name):
        assert index.search_ip(query)[0]["id"] == "unique_unit"
    assert entry.to_dict() == before
    with pytest.raises(ValueError):
        SearchIndex((entry, entry))
    for count in (0, True, 33):
        with pytest.raises(ValueError):
            index.search_ip("unit", k=count)


def test_five_hundred_ip_search_is_below_50ms(catalog):
    library = tuple(replace(catalog[0], id=f"fixture_{index}", display_name=f"fixture_{index}", description="test fixture", tags=("fixture",)) for index in range(500))
    index = SearchIndex(library)
    durations = []
    for _ in range(11):
        started = perf_counter()
        result = index.search_ip("fixture_317", k=8)
        durations.append((perf_counter() - started) * 1000)
        assert result[0]["id"] == "fixture_317"
    assert max(durations) < 50, durations