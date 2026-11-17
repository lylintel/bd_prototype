import json

import pytest

from ai.client import LLMError, ReplayClient
from ai.context import budget_context, estimate_tokens
from ai.pipeline import run_pipeline
from bdai import ProposalStore
from core.design import DesignFormatError
from scripts.synthetic_design import synthetic_design


@pytest.mark.parametrize("count", [500, 2000])
def test_context_budget_full_subgraph_and_explicit_errors(count):
    document, library = synthetic_design(instance_count=count)
    full, details = budget_context(document, library, token_budget=2_000_000)
    assert len(full["instances"]) == count and details["scope"] == "full"
    assert details["estimated_tokens"] == estimate_tokens(full)
    with pytest.raises(LLMError) as raised:
        budget_context(document, library, token_budget=12_000)
    assert raised.value.code == "AI_CONTEXT_SELECTION_REQUIRED"
    subset, details = budget_context(document, library, token_budget=12_000, selected_instances=["unit_0"])
    neighbors = {"unit_0"}
    for net in document["nets"]:
        names = {endpoint["inst"] for endpoint in net["endpoints"]}
        if "unit_0" in names:
            neighbors.update(names)
    assert {item["name"] for item in subset["instances"]} == neighbors
    assert details["scope"] == "subgraph" and details["totals"]["instances"] == count
    assert details["estimated_tokens"] <= 12_000 and details["boundary_nets"] > 0
    with pytest.raises(LLMError) as raised:
        budget_context(document, library, token_budget=512, selected_instances=["unit_0"])
    assert raised.value.code == "AI_CONTEXT_BUDGET"


def test_token_estimate_and_invalid_selection_are_explicit():
    assert estimate_tokens("中文") > estimate_tokens("ab")
    document, library = synthetic_design(instance_count=500)
    with pytest.raises(LLMError):
        budget_context(document, library, token_budget=1000, selected_instances=["invented"])
    with pytest.raises(LLMError):
        budget_context(document, library, token_budget=True)
    assert "coordinates" not in json.dumps(document)


@pytest.mark.parametrize("count", [500, 2000])
def test_pipeline_marks_subgraph_and_rejects_outside_operations(count):
    document, library = synthetic_design(instance_count=count)
    reply = {"schema_version": 1, "ops": [], "summary": "test", "assumptions": [], "questions": [], "missing_ip": []}
    client = ReplayClient([reply])
    result = run_pipeline(document, library, "synthetic_cell", client, context_token_budget=12_000, selected_instances=["unit_0"])
    assert result["validation"]["valid"] and result["context"]["scope"] == "subgraph"
    assert result["document"] == document
    assert len(json.dumps(client.requests).encode()) < 256 * 1024
    outside = next(item["name"] for item in document["instances"] if item["name"] not in result["context"]["included_instances"])
    bad = {**reply, "ops": [{"op": "set_param", "inst": outside, "name": "WIDTH", "value": 8}]}
    blocked = run_pipeline(document, library, "synthetic_cell", ReplayClient([bad] * 3), context_token_budget=12_000, selected_instances=["unit_0"])
    assert not blocked["validation"]["valid"] and blocked["ops"] == []
    assert blocked["validation"]["diagnostics"][0]["code"] == "AI_CONTEXT_SCOPE"
    assert all(outside not in step["affected_ports"] for step in blocked["trace"])
    with pytest.raises(DesignFormatError) as raised:
        ProposalStore(None).check_request({"design": document, "padding": "x" * (256 * 1024)})
    assert raised.value.diagnostic.code == "AI_REQUEST_TOO_LARGE"


def test_private_settings_v1_migrates_budget_without_touching_design(tmp_path, monkeypatch):
    from ai.settings import SettingsStore

    monkeypatch.delenv("BD_AI_API_KEY", raising=False)
    folder = tmp_path / ".bdstudio"
    folder.mkdir()
    path = folder / "ai.json"
    path.write_text(json.dumps({"schema_version": 1, "model": "offline"}), encoding="utf-8")
    settings = SettingsStore(tmp_path)
    assert settings.configuration().context_token_budget == 32_000
    settings.save({"context_token_budget": 12_000})
    assert json.loads(path.read_text())["schema_version"] == 2
    assert SettingsStore(tmp_path).configuration().context_token_budget == 12_000