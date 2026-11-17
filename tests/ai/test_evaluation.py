from copy import deepcopy
import json

import pytest

from ai.client import ReplayClient
from bdstudio.ai_eval import ROOT, REPLAYS, baseline, catalog, evaluate_cases, expected_document, load_cases, load_held_out, main, normalized, score_case, write_report
from core.ops import apply_ops
from core.semantic import validate


def test_scoring_distinguishes_validity_topology_parameters_and_missing_ip():
    expected = {"instances": [["unit", "counter", "1.0.0"]], "connections": [["@clk", "unit.clk"]],
                "params": {"unit.WIDTH": 8}, "ports": {"clk": {"dir": "in", "width": 1, "signed": False}}, "missing_ip": False}
    actual = deepcopy(expected)
    result = score_case(expected, actual, valid=True, forbidden=[])
    assert result["exact_match"] and result["instance_f1"] == result["connection_f1"] == 1
    actual["params"]["unit.WIDTH"] = 12
    actual["connections"] = []
    result = score_case(expected, actual, valid=True, forbidden=[])
    assert result["valid"] and not result["exact_match"]
    assert result["connection_f1"] == 0 and result["diff"]["params"]
    actual["missing_ip"] = True
    assert not score_case(expected, actual, valid=False, forbidden=[])["missing_ip_correct"]


def test_empty_outputs_cannot_pass_nonempty_design_expectations():
    expected = {"instances": [["unit", "counter", "1.0.0"]], "connections": [], "params": {}, "ports": {}, "missing_ip": False}
    actual = {"instances": [], "connections": [], "params": {}, "ports": {}, "missing_ip": False}
    result = score_case(expected, actual, valid=True, forbidden=[])
    assert result["instance_f1"] == 0 and not result["exact_match"]


def test_all_twenty_recordings_cover_expectations_and_traps(tmp_path):
    cases = load_cases()
    recordings = json.loads(REPLAYS.read_text(encoding="utf-8"))
    assert set(recordings) == {item["id"] for item in cases}
    assert sum(item["tier"] == "simple" for item in cases) == 10
    assert sum(item["tier"] == "medium" for item in cases) == 7
    assert {item.get("expression") for item in cases} == {None, "slice", "const", "concat"}
    report = evaluate_cases(cases, catalog(), lambda case: ReplayClient(recordings[case["id"]]))
    assert report["count"] == 20
    assert all(item["passed"] for item in report["cases"]), report["cases"]
    assert report["metrics"]["retrieval_top8_hit_rate"] >= 0.9
    report["client"] = "mock"
    write_report(report, tmp_path, deepcopy(report))
    assert report["comparison"]["regressions"] == []
    assert (tmp_path / "report.md").is_file()


def test_corrupt_recording_produces_case_diff_and_regression(tmp_path):
    cases = load_cases()
    recordings = json.loads(REPLAYS.read_text(encoding="utf-8"))
    library = catalog()
    previous = evaluate_cases(cases, library, lambda case: ReplayClient(recordings[case["id"]]))
    recordings["clock_tick"][0]["ops"][0]["params"]["HALF_PERIOD"] = 5
    current = evaluate_cases(cases, library, lambda case: ReplayClient(recordings[case["id"]]))
    current["client"] = "mock"
    write_report(current, tmp_path, previous)
    result = next(item for item in current["cases"] if item["id"] == "clock_tick")
    assert result["valid"] and not result["passed"] and result["diff"]["params"]
    assert current["comparison"]["regressions"] == ["clock_tick"]
    assert "HALF_PERIOD" in (tmp_path / "report.md").read_text(encoding="utf-8")


def test_real_mode_requires_explicit_network_permission(tmp_path):
    with pytest.raises(SystemExit) as raised:
        main(["--client", "real", "--report", str(tmp_path)])
    assert raised.value.code == 2


def test_held_out_expectations_are_independent_complete_and_valid():
    cases = load_held_out()
    assert len(cases) == 12
    assert len({case["id"] for case in cases}) == 12
    assert not {case["id"] for case in cases} & {case["id"] for case in load_cases()}
    assert {category: sum(case["category"] == category for case in cases) for category in ("incremental", "long-zh", "large", "trap")} == {"incremental": 4, "long-zh": 4, "large": 2, "trap": 2}
    library = catalog()
    for case in cases:
        if case["category"] == "long-zh":
            assert len(case["prompt"]) >= 200
        if case["category"] == "large":
            assert len(baseline(case, library)["instances"]) >= 30
        assert not [item for item in validate(expected_document(case, library), library) if item.severity == "error"], case["id"]


def test_independent_held_out_replays_match_handwritten_expectations():
    cases = load_held_out()
    recordings = json.loads((ROOT / "tests/ai_eval/held_out_replays.json").read_text(encoding="utf-8"))
    assert set(recordings) == {case["id"] for case in cases}
    library = catalog()
    for case in cases:
        reply = recordings[case["id"]][-1]
        if case["expect"].get("questions"):
            assert reply["questions"] and not reply["ops"]
        else:
            candidate, errors = apply_ops(baseline(case, library), library, reply["ops"])
            assert not [item for item in errors if item.severity == "error"], case["id"]
            assert normalized(candidate, library) == normalized(expected_document(case, library), library), case["id"]