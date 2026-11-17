from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from ai.client import LLMError, ReplayClient
from ai.pipeline import run_pipeline


def response(ops, **extra):
    return {"schema_version": 1, "ops": ops, "summary": "test proposal", "assumptions": [], "missing_ip": [], "questions": [], **extra}


def parameter(instance, name, value):
    return {"op": "set_param", "inst": instance, "name": name, "value": value}


def test_hallucinated_port_is_corrected_with_machine_feedback(bundle):
    document, library = bundle
    before = deepcopy(document)
    disconnect = {"op": "disconnect", "from": {"type": "port", "inst": "counter_0", "port": "count"}, "to": {"type": "port", "inst": "compare_0", "port": "value"}}
    bad = {"op": "connect", "from": {"type": "const", "const": "8'd5"}, "to": {"type": "port", "inst": "compare_0", "port": "invented"}, "net": "count_bus"}
    good = {**bad, "to": {"type": "port", "inst": "compare_0", "port": "value"}}
    client = ReplayClient([response([disconnect, bad]), response([disconnect, good])])
    result = run_pipeline(document, library, "counter compare_eq constant input", client)
    assert result["validation"]["valid"] and result["attempts"] == 2
    feedback = json.loads(client.requests[1]["messages"][-1]["content"])
    assert feedback["diagnostics"][0]["code"] == "OP_UNKNOWN_PORT"
    assert all("message" not in item for item in feedback["diagnostics"])
    assert feedback["affected_ports"]["compare_0"]["value"]["width"] == 8
    assert document == before


def test_three_failed_attempts_never_apply_and_are_bounded(bundle):
    document, library = bundle
    before = deepcopy(document)
    client = ReplayClient([response([parameter("counter_0", "WIDTH", 0)])] * 3)
    result = run_pipeline(document, library, "counter WIDTH", client)
    assert not result["validation"]["valid"] and result["attempts"] == len(client.requests) == 3
    assert document == before
    with pytest.raises(ValueError):
        run_pipeline(document, library, "counter", client, max_attempts=4)


def test_repair_replaces_batch_instead_of_accumulating_failed_edits(bundle):
    document, library = bundle
    client = ReplayClient([response([parameter("counter_0", "WIDTH", 12)]), response([parameter("compare_0", "THRESHOLD", 19)])])
    result = run_pipeline(document, library, "counter compare_eq", client)
    assert result["validation"]["valid"]
    assert result["document"]["instances"][0]["params"]["WIDTH"] == 8


@pytest.mark.parametrize("field,code", [("missing_ip", "AI_MISSING_IP"), ("questions", "AI_CLARIFICATION")])
def test_missing_ip_or_questions_stop_without_applying(bundle, field, code):
    document, library = bundle
    client = ReplayClient([response([parameter("compare_0", "THRESHOLD", 19)], **{field: ["unresolved requirement"]})])
    result = run_pipeline(document, library, "ADC", client)
    assert result["attempts"] == 1 and not result["validation"]["valid"]
    assert result["validation"]["diagnostics"][0]["code"] == code
    assert result["document"] == document and result["ops"] == []


def test_model_cannot_add_an_ip_outside_supplied_cards(bundle):
    document, library = bundle
    operation = {"op": "add_instance", "name": "new", "ip": "invented", "version": "1.0.0"}
    result = run_pipeline(document, library, "counter", ReplayClient([response([operation])] * 3))
    assert not result["validation"]["valid"]
    assert result["validation"]["diagnostics"][0]["code"] == "AI_IP_NOT_RETRIEVED"


def test_prompt_contains_resolved_metadata_and_expression_connections_not_rtl(bundle):
    document, library = bundle
    document["schema_version"] = 3
    document["nets"][2]["endpoints"][0] = {"concat": [{"inst": "counter_0", "port": "count", "slice": [3, 0]}, {"const": "4'd0"}]}
    library = (replace(library[0], description="PRIVATE_RTL_IMPLEMENTATION"), *library[1:])
    client = ReplayClient([response([])])
    run_pipeline(document, library, "counter compare_eq", client)
    messages = client.requests[0]["messages"]
    context = json.loads(messages[2]["content"].split("\n", 1)[1].rsplit("\n", 1)[0])
    assert context["netlist"]["instances"][0]["ports"]["count"]["width"] == 8
    assert context["netlist"]["nets"][2]["endpoints"][0]["concat"][0]["slice"] == [3, 0]
    text = json.dumps(messages)
    assert "PRIVATE_RTL_IMPLEMENTATION" not in text and "project_ips" not in text and '"sources"' not in text
    assert len(context["ip_cards"]) <= 8


def test_transport_failure_does_not_start_semantic_retries(bundle):
    document, library = bundle
    client = ReplayClient([LLMError("AI_LLM_TIMEOUT")])
    result = run_pipeline(document, library, "counter", client)
    assert result["attempts"] == 1 and not result["validation"]["valid"]
    assert result["validation"]["diagnostics"][0]["code"] == "AI_LLM_TIMEOUT"

def test_injected_metadata_cannot_authorize_deletions(bundle):
    document, library = bundle
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/ai-injection.json").read_text(encoding="utf-8"))
    malicious = fixture["description"]
    library = (replace(library[0], description=malicious), *library[1:])
    client = ReplayClient([response(fixture["operations"])] * 3)
    result = run_pipeline(document, library, "counter compare_eq", client)
    assert result["ops"] == [] and result["document"] == document
    assert not result["validation"]["valid"]
    assert malicious not in json.dumps(client.requests, ensure_ascii=False)
    assert "untrusted data" in client.requests[0]["messages"][0]["content"]


@pytest.mark.parametrize("operation", [
    {"op": "shell", "command": "echo injected"},
    {"op": "add_instance", "name": "../outside", "ip": "counter", "version": "1.0.0"},
    {"op": "connect", "from": {"type": "interface", "inst": "counter_0", "port": "count"}, "to": {"type": "port", "inst": "compare_0", "port": "value"}},
])
def test_untrusted_output_cannot_escape_typed_operations(bundle, operation):
    document, library = bundle
    result = run_pipeline(document, library, "counter compare_eq", ReplayClient([response([operation])] * 3))
    assert not result["validation"]["valid"]
    assert result["document"] == document