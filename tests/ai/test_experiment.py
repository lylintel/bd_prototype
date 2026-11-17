from decimal import Decimal
import json

import httpx
import pytest

from ai.client import ClientConfig, LLMError, OpenAIClient
from ai.experiment import CallRecorder, RunBudget, classify_failures, run_experiment, write_experiment_report
from bdstudio.ai_eval import ROOT, REPLAYS, catalog, load_cases, load_held_out, main


def test_call_and_cost_limits_reject_before_a_request():
    budget = RunBudget(max_calls=1, max_cost=Decimal("1"), input_price=Decimal("1"), output_price=Decimal("1"))
    ticket = budget.reserve({"messages": []}, 64)
    budget.settle(ticket, {"prompt_tokens": 10, "completion_tokens": 4})
    assert budget.calls == 1 and budget.accounted_cost == Decimal("0.000014")
    with pytest.raises(LLMError) as raised:
        budget.reserve({"messages": []}, 64)
    assert raised.value.params["reason"] == "max_calls"
    denied = RunBudget(max_calls=400, max_cost=Decimal("0"), input_price=Decimal("1"), output_price=Decimal("1"))
    with pytest.raises(LLMError) as raised:
        denied.reserve({"messages": []}, 64)
    assert raised.value.params["reason"] == "max_cost" and denied.calls == 0


def test_missing_usage_retains_conservative_cost_reservation():
    budget = RunBudget(max_calls=2, max_cost=Decimal("1"), input_price=Decimal("1"), output_price=Decimal("2"))
    ticket = budget.reserve({"messages": [{"content": "test"}]}, 64)
    reserved = budget.accounted_cost
    budget.settle(ticket, None)
    assert budget.accounted_cost == reserved and budget.unknown_usage_calls == 1


def test_json_retry_is_counted_as_a_physical_call_and_cannot_exceed_limit():
    calls = []
    def provider(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "invalid JSON"}}], "usage": {"prompt_tokens": 12, "completion_tokens": 2}})
    budget = RunBudget(max_calls=1, max_cost=Decimal("1"), input_price=Decimal("1"), output_price=Decimal("1"))
    recorder = CallRecorder(budget)
    client = OpenAIClient(ClientConfig(model="test"), transport=httpx.MockTransport(provider), recorder=recorder, max_output_tokens=64)
    with pytest.raises(LLMError) as raised:
        client.generate([{"role": "user", "content": "test"}], {"type": "object"})
    assert raised.value.code == "AI_EVAL_LIMIT"
    assert len(calls) == budget.calls == len(recorder.events) == 1
    assert calls[0]["max_tokens"] == 64
    assert recorder.events[0]["usage_source"] == "provider"


def test_three_repeats_measure_first_pass_repair_gain_and_consistency(tmp_path):
    recordings = json.loads(REPLAYS.read_text(encoding="utf-8"))
    budget = RunBudget(max_calls=20, max_cost=0, input_price=0, output_price=0)
    report = run_experiment(load_cases()[:1], catalog(), recordings, budget=budget)
    assert report["planned_trials"] == report["completed_trials"] == 3
    assert report["metrics"]["first_pass_rate"] == 0
    assert report["metrics"]["final_pass_rate"] == 1
    assert report["metrics"]["outcome_consistency"] == 1
    assert report["metrics"]["average_actual_tokens"] is None
    assert report["metrics"]["average_estimated_tokens"] > 0
    assert report["calls"] == 6
    write_experiment_report(report, tmp_path)
    assert (tmp_path / "report.json").is_file() and (tmp_path / "report.md").is_file()


def test_budget_stop_writes_an_honest_partial_report(tmp_path):
    recordings = json.loads(REPLAYS.read_text(encoding="utf-8"))
    budget = RunBudget(max_calls=1, max_cost=0, input_price=0, output_price=0)
    report = run_experiment(load_cases()[:1], catalog(), recordings, budget=budget)
    assert report["status"] == "partial" and report["calls"] == 1
    assert report["completed_trials"] == 0 and report["not_run_trials"] == 2
    assert report["stop_reason"] == "max_calls"
    write_experiment_report(report, tmp_path)
    persisted = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert persisted["metrics"]["final_pass_rate"] is None


def test_cost_stop_has_zero_requests_and_all_trials_unrun(tmp_path):
    recordings = json.loads(REPLAYS.read_text(encoding="utf-8"))
    budget = RunBudget(max_calls=400, max_cost=0, input_price=1, output_price=1)
    report = run_experiment(load_cases()[:1], catalog(), recordings, budget=budget)
    assert report["stop_reason"] == "max_cost" and report["calls"] == 0
    assert report["completed_trials"] == 0 and report["not_run_trials"] == 3
    write_experiment_report(report, tmp_path)
    assert (tmp_path / "report.json").is_file()


def test_all_dev_and_held_out_trials_are_counted_without_dropping_failures():
    cases = load_cases() + load_held_out()
    recordings = json.loads(REPLAYS.read_text(encoding="utf-8"))
    recordings.update(json.loads((ROOT / "tests/ai_eval/held_out_replays.json").read_text(encoding="utf-8")))
    budget = RunBudget(max_calls=400, max_cost=0, input_price=0, output_price=0)
    report = run_experiment(cases, catalog(), recordings, budget=budget)
    assert report["count"] == 32 and report["completed_trials"] == 96
    assert report["groups"]["split"]["dev"]["trials"] == 60
    assert report["groups"]["split"]["held-out"]["trials"] == 36
    assert len(report["trials"]) == 96
    assert report["client"] == "mock" and not report["real_model_called"]


def test_real_dry_run_without_configuration_never_sends(tmp_path, monkeypatch):
    for name in ("BD_AI_API_KEY", "BD_AI_BASE_URL", "BD_AI_MODEL", "BD_AI_INPUT_PRICE", "BD_AI_OUTPUT_PRICE"):
        monkeypatch.delenv(name, raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run must not send")
    monkeypatch.setattr(OpenAIClient, "_request", forbidden)
    folder = tmp_path / "report"
    assert main(["--client", "real", "--allow-network", "--dry-run", "--workspace", str(tmp_path), "--report", str(folder), "--max-cost", "0"]) == 0
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "waiting_configuration"
    assert report["calls"] == 0 and not report["real_model_called"]
    assert report["planned_trials"] == report["not_run_trials"] == 96
    assert report["metrics"]["first_pass_rate"] is None
    assert report["readiness"]["expected_designs_valid"] == 32


@pytest.mark.parametrize("code,kind", [("OP_UNKNOWN_IP", "wrong_ip"), ("OP_UNKNOWN_PORT", "hallucinated_port_parameter"),
    ("E001", "width_slice"), ("E003", "missing_connections"), ("E002", "extra_connections"),
    ("AI_LLM_RESPONSE", "json_schema"), ("AI_OPERATION_FORBIDDEN", "injection_influenced")])
def test_failure_taxonomy_is_based_on_structured_evidence(code, kind):
    score = {"valid": False, "passed": False, "diff": {}}
    outcome = {"attempts": 3, "trace": [], "validation": {"diagnostics": [{"code": code}]}}
    found = classify_failures(score, outcome, injected=True)
    assert kind in found and "retry_limit" in found


def test_ignored_missing_ip_and_comparison_regressions(tmp_path):
    score = {"valid": True, "passed": False, "diff": {"missing_ip": {"expected": True, "actual": False}}}
    outcome = {"attempts": 1, "trace": [], "validation": {"diagnostics": []}}
    assert "ignored_missing_ip" in classify_failures(score, outcome)
    cases = [next(case for case in load_cases() if case["id"] == "clock_tick")]
    recordings = json.loads(REPLAYS.read_text(encoding="utf-8"))
    previous = run_experiment(cases, catalog(), recordings, budget=RunBudget(max_calls=20, max_cost=0, input_price=0, output_price=0))
    previous["dataset_sha256"] = "fixture-cohort"
    recordings["clock_tick"][0]["ops"][0]["params"]["HALF_PERIOD"] = 5
    current = run_experiment(cases, catalog(), recordings, budget=RunBudget(max_calls=20, max_cost=0, input_price=0, output_price=0))
    current["dataset_sha256"] = "fixture-cohort"
    result = write_experiment_report(current, tmp_path, previous=previous)
    assert result["comparison"]["comparable"] and result["comparison"]["regressions"] == ["clock_tick"]


def test_real_mode_has_no_endpoint_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("BD_AI_BASE_URL", raising=False)
    monkeypatch.setenv("BD_AI_MODEL", "test-model")
    monkeypatch.setenv("BD_AI_API_KEY", "unit-test-private-key")
    def forbidden(*args, **kwargs):
        raise AssertionError("must not guess an endpoint")
    monkeypatch.setattr(OpenAIClient, "_request", forbidden)
    folder = tmp_path / "report"
    code = main(["--client", "real", "--allow-network", "--workspace", str(tmp_path), "--report", str(folder),
                 "--max-cost", "1", "--input-price", "1", "--output-price", "1"])
    assert code == 2
    text = (folder / "report.json").read_text(encoding="utf-8")
    report = json.loads(text)
    assert report["calls"] == 0 and "endpoint" in report["readiness"]["missing"]
    assert "unit-test-private-key" not in text and "api.openai.com" not in text


def test_provider_accounting_overrun_stops_further_calls():
    budget = RunBudget(max_calls=20, max_cost=1, input_price=1, output_price=1)
    ticket = budget.reserve({"messages": []}, 4)
    budget.settle(ticket, {"prompt_tokens": 10, "completion_tokens": 5})
    assert budget.stop_reason == "provider_exceeded_reservation"
    with pytest.raises(LLMError):
        budget.reserve({"messages": []}, 4)
    assert budget.calls == 1


def test_recorded_sensitive_reply_is_redacted_even_when_rejected():
    key, endpoint = "unit-test-private-key", "https://private.example.invalid/v1"
    recorder = CallRecorder(RunBudget(max_calls=2, max_cost=1, input_price=1, output_price=1), secrets=(key, endpoint, "private.example.invalid"))
    content = json.dumps({"value": key + " " + endpoint}).replace("unit", r"\u0075nit")
    client = OpenAIClient(ClientConfig(model="test", api_key=key, base_url=endpoint), recorder=recorder, max_output_tokens=64,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": [{"message": {"content": content}}]})))
    with pytest.raises(LLMError) as raised:
        client.generate([{"role": "user", "content": "test"}], {"type": "object"})
    assert raised.value.code == "AI_LLM_SENSITIVE_RESPONSE"
    recorded = json.dumps(recorder.events)
    assert all(value not in recorded for value in (key, "private.example.invalid", "Authorization"))