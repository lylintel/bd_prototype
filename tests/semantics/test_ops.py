from copy import deepcopy
from pathlib import Path

import pytest

import bdtool
from core.ops import apply_ops
from core.semantic import validate


def port(instance, name):
    return {"type": "port", "inst": instance, "port": name}


def test_interface_ops_require_v2_and_preserve_atomic_bus_facts():
    from tests.semantics.test_interfaces import axis_pair_data

    document, library = axis_pair_data()
    document['interface_connections'] = []
    operation = {'op': 'connect', 'net': 'link', 'from': {'type': 'interface', 'inst': 'first', 'interface': 'm_axis'},
                 'to': {'type': 'interface', 'inst': 'second', 'interface': 's_axis'}}
    original = deepcopy(document)
    rejected, errors = apply_ops(document, library, [operation])
    assert rejected == original and errors[0].code == 'OP_ENDPOINT_TYPE'
    connected, errors = apply_ops(document, library, {'schema_version': 2, 'ops': [operation]})
    assert not errors
    assert connected['nets'] == original['nets']
    assert connected['interface_connections'] == [{'name': 'link', 'from': {'inst': 'first', 'interface': 'm_axis'},
                                                   'to': {'inst': 'second', 'interface': 's_axis'}}]
    assert document == original
    assert apply_ops(connected, library, {'schema_version': 2, 'ops': [operation]}) == (connected, [])
    disconnected, errors = apply_ops(connected, library, {'schema_version': 2, 'ops': [{**operation, 'op': 'disconnect'}]})
    assert disconnected == original and {item.code for item in errors} == {'E003'}
    rollback, errors = apply_ops(document, library, {'schema_version': 2, 'ops': [operation, {'op': 'remove_instance', 'name': 'missing'}]})
    assert rollback == original and errors[0].code == 'OP_UNKNOWN_INSTANCE'


@pytest.mark.parametrize('target,code', [
    ({'type': 'port', 'inst': 'second', 'port': 's_data'}, 'E210'),
    ({'type': 'interface', 'inst': 'second', 'interface': 's_axis', 'confirmed': True}, 'OP_SCHEMA'),
    ({'type': 'interface', 'inst': 'second', 'interface': 'invented'}, 'E203'),
    ({'type': 'interface', 'inst': 'second.child', 'interface': 's_axis'}, 'OP_IDENTIFIER'),
    ({'type': 'concat', 'concat': [{'type': 'interface', 'inst': 'second', 'interface': 's_axis'}]}, 'E210'),
])
def test_interface_ops_reject_mixed_nested_forged_and_cross_layer_endpoints(target, code):
    from tests.semantics.test_interfaces import axis_pair_data

    document, library = axis_pair_data()
    operation = {'op': 'connect', 'from': {'type': 'interface', 'inst': 'first', 'interface': 'm_axis'}, 'to': target}
    result, errors = apply_ops(document, library, {'schema_version': 2, 'ops': [operation]})
    assert result == document and errors[0].code == code


def test_interface_ops_migrate_only_a_candidate_and_keep_semantic_errors_visible():
    from core.ops import typed_endpoint, validate_operations
    from tests.semantics.test_interfaces import axis_pair_data

    document, library = axis_pair_data()
    operation = {'op': 'connect', 'net': 'link', 'from': typed_endpoint({'inst': 'first', 'interface': 'm_axis'}),
                 'to': typed_endpoint({'inst': 'second', 'interface': 's_axis'})}
    document.update(schema_version=4)
    document.pop('interfaces')
    document.pop('interface_connections')
    before = deepcopy(document)
    result, errors = apply_ops(document, library, {'schema_version': 2, 'ops': [operation]})
    assert not errors and result['schema_version'] == 5 and document == before
    assert result['nets'] == before['nets']
    changed, errors = apply_ops(result, library, {'schema_version': 2, 'ops': [{'op': 'set_param', 'inst': 'second', 'name': 'WIDTH', 'value': 16}]})
    assert 'E204' in {item.code for item in errors}
    assert changed['interface_connections'] == result['interface_connections']
    removed, errors = apply_ops(result, library, {'schema_version': 2, 'ops': [{'op': 'remove_instance', 'name': 'second'}]})
    assert removed['interface_connections'] == []
    assert all(item['name'] != 'second' for item in removed['instances'])
    assert validate_operations({'schema_version': 1, 'ops': []}) == []


def test_interface_ops_external_endpoints_are_mirrored_without_implicit_optional_fixes():
    from core.ops import typed_endpoint
    from tests.semantics.test_interfaces import axis_pair_data

    document, library = axis_pair_data()
    document['interfaces'] = [{'name': 'output_stream', 'protocol': 'axi-stream', 'definition_version': '1.0.0',
        'profile': 'ready-valid', 'mode': 'master', 'parameters': {'DATA_WIDTH': '8'}, 'confirmed': True,
        'signals': {'tdata': 'out_data', 'tvalid': 'out_valid', 'tready': 'out_ready'}}]
    document['nets'] = [net for net in document['nets'] if not net['name'].startswith('out_')]
    operation = {'op': 'connect', 'net': 'output_link', 'from': typed_endpoint({'inst': 'second', 'interface': 'm_axis'}),
                 'to': typed_endpoint({'ext_interface': 'output_stream'})}
    result, errors = apply_ops(document, library, {'schema_version': 2, 'ops': [operation]})
    assert not errors and len(result['interface_connections']) == 2
    assert result['nets'] == document['nets']
    document['ports']['out_last'] = {'direction': 'output'}
    document['interfaces'][0]['signals']['tlast'] = 'out_last'
    mismatch, errors = apply_ops(document, library, {'schema_version': 2, 'ops': [operation]})
    assert 'E207' in {item.code for item in errors}
    assert mismatch['nets'] == document['nets']
    assert not any('const' in endpoint for net in mismatch['nets'] for endpoint in net['endpoints'])


def test_interface_ops_count_real_nested_expansion_against_4096_limit():
    from core.hierarchy import collapse_design
    from tests.semantics.test_interfaces import axis_pair_data

    document, library = axis_pair_data()
    unit = collapse_design(document, library, ['first', 'second'], 'unit')
    bank = collapse_design(unit, library, ['unit'], 'bank')
    child = bank['subdesigns']['bank']
    for ordinal in range(15):
        name = f'unit_{ordinal}'
        child['instances'].append({'name': name, 'ip': {'id': 'unit', 'version': '1.0.0'}})
        for net in child['nets']:
            if any(endpoint.get('ext') and child['ports'][endpoint['ext']]['direction'] == 'input' for endpoint in net['endpoints']):
                original = next(endpoint for endpoint in net['endpoints'] if endpoint.get('inst') == 'unit')
                net['endpoints'].append({**original, 'inst': name})
    assert not [item for item in validate(bank, library) if item.severity == 'error']
    commands = [{'op': 'add_instance', 'ip': 'bank', 'version': '1.0.0', 'name': f'bank_{ordinal}'} for ordinal in range(86)]
    accepted_draft, errors = apply_ops(bank, library, {'schema_version': 2, 'ops': commands[:85]})
    assert len(accepted_draft['instances']) == 86
    assert {item.code for item in errors} == {'E003'}
    assert not any(item['id'] in ('bank', 'unit') for item in accepted_draft['project_ips'])
    rejected, errors = apply_ops(bank, library, {'schema_version': 2, 'ops': commands})
    assert rejected == bank and errors[0].code == 'OP_INTERFACE_LIMIT'
    assert errors[0].params == {'limit': 4096, 'expanded_signals': 4128}


@pytest.mark.parametrize("name,ip,version,code", [
    ("extra", "compare_eq", "1.0.0", "E003"),
    ("counter_0", "counter", "1.0.0", "OP_DUPLICATE_NAME"),
    ("extra", "missing", "1.0.0", "OP_UNKNOWN_IP"),
    ("extra", "counter", "9.0.0", "OP_UNKNOWN_IP"),
    ("module", "counter", "1.0.0", "OP_IDENTIFIER"),
])
def test_add_instance_contract(bundle, name, ip, version, code):
    document, library = bundle
    result, errors = apply_ops(document, library, [{"op": "add_instance", "name": name, "ip": ip, "version": version}])
    assert code in {item.code for item in errors}
    assert (len(result["instances"]) == 3) if code == "E003" else result == document


@pytest.mark.parametrize("name,code", [("counter_0", "E003"), ("compare_0", "E003"), ("missing", "OP_UNKNOWN_INSTANCE"), ("bad.name", "OP_IDENTIFIER")])
def test_remove_instance_contract(bundle, name, code):
    document, library = bundle
    result, errors = apply_ops(document, library, [{"op": "remove_instance", "name": name}])
    assert code in {item.code for item in errors}
    if code == "E003":
        assert all(item["name"] != name for item in result["instances"])
        repeated, errors = apply_ops(result, library, [{"op": "remove_instance", "name": name}])
        assert errors[0].code == "OP_UNKNOWN_INSTANCE" and repeated == result
    else:
        assert result == document


@pytest.mark.parametrize("instance,name,value,code", [
    ("compare_0", "THRESHOLD", 19, None), ("compare_0", "THRESHOLD", "3 * 7", None),
    ("compare_0", "THRESHOLD", -1, "OP_INVALID_PARAM"), ("compare_0", "UNKNOWN", 4, "OP_UNKNOWN_PARAMETER"),
    ("missing", "WIDTH", 4, "OP_UNKNOWN_INSTANCE"),
])
def test_set_parameter_contract(bundle, instance, name, value, code):
    document, library = bundle
    operations = [{"op": "set_param", "inst": instance, "name": name, "value": value}]
    result, errors = apply_ops(document, library, operations)
    if code:
        assert errors[0].code == code and result == document
    else:
        assert not errors and result["instances"][1]["params"][name] == value
        assert apply_ops(result, library, operations) == (result, [])


@pytest.mark.parametrize("name,width,code", [("enable", "1", None), ("data", "4 * 2", None), ("clk", "1", "OP_DUPLICATE_NAME"), ("bad.name", "1", "OP_IDENTIFIER"), ("empty", "0", "OP_INVALID_WIDTH")])
def test_add_external_port_contract(bundle, name, width, code):
    document, library = bundle
    result, errors = apply_ops(document, library, [{"op": "add_external_port", "name": name, "dir": "in", "width": width}])
    if code:
        assert errors[0].code == code and result == document
    else:
        assert not errors and result["ports"][name]["direction"] == "input"
        assert result["ports"][name].get("range") == (None if width == "1" else [7, 0])


@pytest.mark.parametrize("target,code", [
    (port("compare_0", "value"), None), (port("missing", "value"), "OP_UNKNOWN_INSTANCE"),
    (port("compare_0", "missing"), "OP_UNKNOWN_PORT"), ({"type": "interface", "name": "bus"}, "OP_ENDPOINT_TYPE"),
])
def test_connect_contract(bundle, target, code):
    document, library = bundle
    operation = {"op": "connect", "from": port("counter_0", "count"), "to": target, "net": "count_bus"}
    result, errors = apply_ops(document, library, [operation])
    if code:
        assert errors[0].code == code and result == document
    else:
        assert not errors and result == document


@pytest.mark.parametrize("source,target,code", [
    (port("counter_0", "count"), port("compare_0", "value"), "E003"),
    ({"type": "port", "ext": "clk"}, port("counter_0", "clk"), "E003"),
    (port("missing", "count"), port("compare_0", "value"), "OP_UNKNOWN_INSTANCE"),
    (port("counter_0", "count"), {"type": "port", "ext": "match"}, "OP_NOT_CONNECTED"),
])
def test_disconnect_contract(bundle, source, target, code):
    document, library = bundle
    operation = {"op": "disconnect", "from": source, "to": target}
    result, errors = apply_ops(document, library, [operation])
    assert code in {item.code for item in errors}
    if code == "E003":
        _, repeated = apply_ops(result, library, [operation])
        assert repeated[0].code == "OP_NOT_CONNECTED"
    else:
        assert result == document


@pytest.mark.parametrize("endpoint", [
    {"type": "slice", "inst": "counter_0", "port": "count", "slice": [7, 0]},
    {"type": "const", "const": "8'd5"},
    {"type": "concat", "concat": [{"type": "slice", "inst": "counter_0", "port": "count", "slice": [3, 0]}, {"type": "const", "const": "4'd0"}]},
])
def test_typed_expressions_reuse_v3_semantics_and_upgrade_a_copy(bundle, endpoint):
    document, library = bundle
    operations = [
        {"op": "disconnect", "from": port("counter_0", "count"), "to": port("compare_0", "value")},
        {"op": "connect", "from": endpoint, "to": port("compare_0", "value"), "net": "count_bus"},
    ]
    result, errors = apply_ops(document, library, operations)
    assert not errors
    assert result["schema_version"] == 3 and document["schema_version"] == 2
    assert not any(item.severity == "error" for item in validate(result, library))
    assert all("type" not in item for net in result["nets"] for item in net["endpoints"])


def test_batch_is_pure_atomic_and_uses_new_semantic_validation(bundle, monkeypatch):
    document, library = bundle
    original = deepcopy(document)
    operations = [{"op": "set_param", "inst": "counter_0", "name": "WIDTH", "value": 12}]
    def forbidden(*args, **kwargs):
        raise AssertionError("legacy validation or file IO is forbidden")
    monkeypatch.setattr(bdtool, "validate_design", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    result, errors = apply_ops(document, library, operations)
    assert errors[0].code == "E001" and result != document
    result, errors = apply_ops(document, library, [*operations, {"op": "remove_instance", "name": "missing"}])
    assert errors[0].code == "OP_UNKNOWN_INSTANCE" and result == original
    assert document == original


@pytest.mark.parametrize("operations,code", [
    ([{"op": "arbitrary_code", "code": "anything"}], "OP_UNKNOWN_OPERATION"),
    ([{"op": "set_param", "inst": "counter_0", "name": "WIDTH", "value": True}], "OP_SCHEMA"),
    ([{"op": "remove_instance", "name": "missing"}] * 201, "OP_LIMIT"),
    ({"schema_version": 99, "ops": []}, "OP_SCHEMA"),
])
def test_operation_payload_limits_and_unknown_commands(bundle, operations, code):
    document, library = bundle
    result, errors = apply_ops(document, library, operations)
    assert result == document and errors[0].code == code