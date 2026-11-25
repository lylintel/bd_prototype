import json
from dataclasses import replace
from pathlib import Path

import pytest

from ai.client import LLMError, ReplayClient
from ai.context import budget_context, estimate_tokens, metadata_card
from ai.pipeline import run_pipeline
from bdai import ProposalStore
from core.design import DesignFormatError
from scripts.synthetic_design import synthetic_design


def test_interface_cards_and_netlist_include_only_confirmed_structural_facts():
    from ai.context import compact_design
    from core.hierarchy import collapse_design
    from tests.semantics.test_interfaces import axis_pair_data

    document, library = axis_pair_data()
    card = metadata_card(library[0])
    output = next(item for item in card['interfaces'] if item['name'] == 'm_axis')
    assert output['parameters']['DATA_WIDTH'] == 8
    assert output['parameter_expressions']['DATA_WIDTH'] == 'WIDTH'
    assert output['signals']['tready'] == {'port': 'm_ready', 'direction': 'in', 'width': 1}
    assert set(output['missing_optional_signals']) == {'tkeep', 'tstrb', 'tlast', 'tid', 'tdest', 'tuser'}
    unconfirmed = replace(library[0], interfaces=tuple({**item, 'confirmed': False} for item in library[0].interfaces))
    assert 'interfaces' not in metadata_card(unconfirmed)
    folded = collapse_design(document, library, ['first'], 'stream_group')
    netlist = compact_design(folded, library)
    group = next(item for item in netlist['instances'] if item['name'] == 'stream_group')
    assert group['hierarchical'] and group['interfaces'][0]['occupied']
    assert group['interfaces'][0]['connections'] == ['link']
    assert group['interfaces'][0]['effective_mode'] == 'master'
    assert netlist['interface_connections'] == folded['interface_connections']
    assert all('__bd_if_' not in net['name'] for net in netlist['nets'])
    assert all(key not in json.dumps(netlist) for key in ('project_ips', 'subdesigns', 'source', 'sha256'))


def test_interface_subgraph_includes_whole_bus_neighbors_and_rejects_partial_context():
    from copy import deepcopy
    from tests.semantics.test_interfaces import axis_pair_data

    document, library = axis_pair_data()
    original_instances, original_links = deepcopy(document['instances']), deepcopy(document['interface_connections'])
    document['instances'] = []
    document['interface_connections'] = []
    document['nets'] = []
    for ordinal in range(30):
        for instance in original_instances:
            document['instances'].append({**deepcopy(instance), 'name': f"{instance['name']}_{ordinal}"})
        connection = deepcopy(original_links[0])
        connection['name'] = f'link_{ordinal}'
        for key in ('from', 'to'):
            connection[key]['inst'] += f'_{ordinal}'
        document['interface_connections'].append(connection)
    subset, details = budget_context(document, library, token_budget=10_000, selected_instances=['first_0'])
    assert details['scope'] == 'subgraph'
    assert {item['name'] for item in subset['instances']} == {'first_0', 'second_0'}
    assert subset['interface_connections'] == [document['interface_connections'][0]]
    assert details['totals']['interface_connections'] == 30
    assert details['estimated_tokens'] <= 10_000
    with pytest.raises(LLMError) as raised:
        budget_context(document, library, token_budget=512, selected_instances=['first_0'])
    assert raised.value.code == 'AI_CONTEXT_BUDGET'


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
    assert json.loads(path.read_text())["schema_version"] == 4
    assert SettingsStore(tmp_path).configuration().context_token_budget == 12_000
    assert settings.configuration().send_ip_descriptions is False
    settings.save({"send_ip_descriptions": True})
    assert SettingsStore(tmp_path).configuration().send_ip_descriptions is True


def test_descriptions_are_opt_in_bounded_and_cleaned(bundle):
    _, library = bundle
    metadata = replace(library[0], description="<b>计数模块</b><script>hidden_secret()</script>\u202e\x00" + "长" * 250)
    assert "description" not in metadata_card(metadata)
    card = metadata_card(metadata, include_description=True)
    assert len(card["description"]) == 200
    assert card["description"].startswith("计数模块")
    assert all(value not in card["description"] for value in ("<b>", "hidden_secret", "\u202e", "\x00"))


def test_builtin_description_policy_cannot_be_forged_by_name():
    from bdip import load_ip
    from ai.retrieval import SearchIndex

    root = Path(__file__).resolve().parents[2]
    builtin = load_ip(root / "ip_library/builtin/bd_counter/1.0.0/ip.json")
    assert "description" in SearchIndex([builtin]).search_ip("bd_counter", builtin_descriptions=True)[0]
    forged = replace(builtin, description="private imported metadata")
    assert "description" not in SearchIndex([forged]).search_ip("bd_counter", builtin_descriptions=True)[0]


def test_malicious_description_is_data_even_when_explicitly_enabled(bundle):
    document, library = bundle
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/ai-injection.json").read_text(encoding="utf-8"))
    library = (replace(library[0], description=fixture["description"]), *library[1:])
    response = {"schema_version": 1, "ops": fixture["operations"], "summary": "test", "assumptions": [], "questions": [], "missing_ip": []}
    client = ReplayClient([response] * 3)
    result = run_pipeline(document, library, "counter compare_eq", client, send_ip_descriptions=True)
    data = client.requests[0]["messages"][2]["content"]
    assert data.startswith("BEGIN_BD_DATA\n") and fixture["description"] in data
    assert result["ops"] == [] and not result["validation"]["valid"] and result["document"] == document