from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from bdgui import Workspace
from bdip import IpMetadata
from bdsemantic import prepare
from core.design import DesignFormatError, check_document, load_document, migrate
from core.generation import generate_artifacts, generate_files
from core.persistence import canonical_document, write_project
from core.semantic import apply_fix, inspect_design


ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).parent / 'golden/interfaces-compat.json'
CASES = {'flat': 'examples/counter_compare.json', 'hierarchy': 'examples/hierarchy/counter.json',
         'expressions': 'examples/semantic/connections.json'}


def baseline(case):
    path = ROOT / CASES[case]
    raw = json.loads(path.read_text(encoding='utf-8'))
    document, library = prepare(Workspace(ROOT, CASES[case]), raw, path.parent.relative_to(ROOT).as_posix())
    return migrate(document, library, target_version=4), library


def outputs(document, library, mode):
    if mode == 'legacy':
        result = inspect_design(document, library)
        assert result['valid'], result['diagnostics']
        return result['files']
    return generate_files(document, library, language=mode)


@pytest.mark.parametrize('case', CASES)
@pytest.mark.parametrize('mode', ['legacy', 'v', 'sv'])
def test_v4_interface_freeze_remains_exact(case, mode):
    document, library = baseline(case)
    expected = json.loads(GOLDEN.read_text(encoding='utf-8'))
    assert outputs(document, library, mode) == expected[case][mode]


@pytest.mark.parametrize('case', CASES)
@pytest.mark.parametrize('mode', ['legacy', 'v', 'sv'])
def test_v5_without_interfaces_matches_frozen_v4_bytes(case, mode):
    document, library = baseline(case)
    before = deepcopy(document)
    upgraded = migrate(document, library, target_version=5)
    expected = json.loads(GOLDEN.read_text(encoding='utf-8'))
    assert outputs(upgraded, library, mode) == expected[case][mode]
    assert upgraded['schema_version'] == 5
    assert document == before


@pytest.mark.parametrize('case', CASES)
def test_interface_migration_is_explicit_one_way_and_roundtrips(case, tmp_path):
    document, library = baseline(case)
    source = ROOT / CASES[case]
    original_bytes = source.read_bytes()
    assert migrate(document, library) == document
    upgraded = migrate(document, library, target_version=5)
    check_document(upgraded)
    assert upgraded['interfaces'] == [] and upgraded['interface_connections'] == []
    assert migrate(upgraded, library) == upgraded
    assert migrate(upgraded, library, target_version=5) == upgraded
    with pytest.raises(DesignFormatError):
        migrate(upgraded, library, target_version=4)
    target = tmp_path / 'migrated.json'
    write_project(upgraded, {'schema_version': 1, 'nodes': {}}, target, {source}, tmp_path)
    restored = load_document(target.read_text(encoding='utf-8'))
    check_document(restored)
    assert restored == canonical_document(upgraded)
    assert source.read_bytes() == original_bytes
    assert document['schema_version'] == 4


def test_legacy_root_cannot_hide_a_v5_child():
    document, library = baseline('hierarchy')
    upgraded = migrate(document, library, target_version=5)
    document['subdesigns'] = upgraded['subdesigns']
    with pytest.raises(DesignFormatError):
        check_document(document)


def test_compatibility_stage_does_not_silently_drop_unimplemented_interfaces():
    document, library = baseline('flat')
    upgraded = migrate(document, library, target_version=5)
    upgraded['interface_connections'] = [{'name': 'unimplemented'}]
    with pytest.raises(DesignFormatError):
        generate_files(upgraded, library)


def axis_pair_data():
    directory = ROOT / 'ip_library/builtin/bd_stream_slice/1.0.0'
    raw = json.loads((directory / 'ip.json').read_text(encoding='utf-8'))
    raw.update(schema_version=2, version='1.1.0')
    raw['interfaces'] = [{
        'name': f'{prefix}_axis', 'protocol': 'axi-stream', 'definition_version': '1.0.0', 'profile': 'ready-valid',
        'mode': mode, 'parameters': {'DATA_WIDTH': 'WIDTH'}, 'confirmed': True,
        'signals': {'tdata': f'{prefix}_data', 'tvalid': f'{prefix}_valid', 'tready': f'{prefix}_ready'},
    } for prefix, mode in [('s', 'slave'), ('m', 'master')]]
    metadata = IpMetadata.from_dict(raw, base_dir=directory)
    ports = {name: {'direction': direction, **({'range': [7, 0]} if name.endswith('data') else {})}
             for name, direction in [('clk', 'input'), ('rst', 'input'), ('in_data', 'input'), ('in_valid', 'input'),
                                     ('in_ready', 'output'), ('out_data', 'output'), ('out_valid', 'output'), ('out_ready', 'input')]}
    nets = [{'name': f'{name}_net', 'endpoints': [{'ext': name}, {'inst': 'first', 'port': name}, {'inst': 'second', 'port': name}]}
            for name in ('clk', 'rst')]
    nets.extend({'name': f'{external}_net', 'endpoints': [{'ext': external}, {'inst': instance, 'port': port}]}
                for external, instance, port in [('in_data', 'first', 's_data'), ('in_valid', 'first', 's_valid'),
                    ('in_ready', 'first', 's_ready'), ('out_data', 'second', 'm_data'), ('out_valid', 'second', 'm_valid'),
                    ('out_ready', 'second', 'm_ready')])
    document = {'schema_version': 5, 'name': 'axis_pair', 'ports': ports, 'nets': nets, 'subdesigns': {}, 'interfaces': [],
        'instances': [{'name': name, 'ip': {'id': metadata.id, 'version': metadata.version}, 'params': {'WIDTH': 8}}
                      for name in ('first', 'second')],
        'interface_connections': [{'name': 'link', 'from': {'inst': 'first', 'interface': 'm_axis'},
                                  'to': {'inst': 'second', 'interface': 's_axis'}}]}
    return document, (metadata,)


@pytest.fixture
def axis_pair():
    return axis_pair_data()


def axis_scalar_reference(document):
    reference = deepcopy(document)
    reference['schema_version'] = 4
    reference.pop('interfaces')
    reference.pop('interface_connections')
    reference['nets'].extend([
        {'name': '__bd_if_link__tdata', 'endpoints': [{'inst': 'first', 'port': 'm_data'}, {'inst': 'second', 'port': 's_data'}]},
        {'name': '__bd_if_link__tvalid', 'endpoints': [{'inst': 'first', 'port': 'm_valid'}, {'inst': 'second', 'port': 's_valid'}]},
        {'name': '__bd_if_link__tready', 'endpoints': [{'inst': 'second', 'port': 's_ready'}, {'inst': 'first', 'port': 'm_ready'}]},
    ])
    return reference


@pytest.mark.parametrize('language', ['v', 'sv'])
def test_axis_generated_hdl_matches_independent_signal_reference(axis_pair, language):
    document, library = axis_pair
    reference = generate_files(axis_scalar_reference(document), library, language=language)
    expected = {name: text.replace('schema_version: 4', 'schema_version: 5', 1) for name, text in reference.items()}
    assert generate_files(document, library, language=language) == expected
    if language == 'v':
        frozen = json.loads((Path(__file__).parent / 'golden/axis-pair.json').read_text(encoding='utf-8'))
        assert expected == frozen


@pytest.mark.parametrize('language', ['v', 'sv'])
def test_axis_strict_tools_and_icarus_handshake(axis_pair, tmp_path, language):
    from bdcheck import run_checks

    document, library = axis_pair
    files = generate_files(document, library, language=language)
    source = library[0].base_dir / library[0].source.path
    checked = run_checks(files, [source], 'axis_pair_wrapper', workspace_root=ROOT, strict_lint=True)
    assert checked['valid'], checked['diagnostics']
    assert checked['strict_lint'] and not checked['diagnostics']
    assert next(tool for tool in checked['tools'] if tool['name'] == 'yosys')['cell_count'] > 0
    generated = []
    for name, text in files.items():
        target = tmp_path / name
        target.write_text(text, encoding='utf-8')
        generated.append(str(target))
    compiled = subprocess.run([shutil.which('iverilog'), '-g2012', '-s', 'tb', '-o', str(tmp_path / 'simulation'),
        *generated, str(source), str(ROOT / 'tests/fixtures/interfaces/axis_pair_tb.sv')], capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0 and not compiled.stderr.strip(), compiled.stderr
    simulated = subprocess.run([shutil.which('vvp'), str(tmp_path / 'simulation')], capture_output=True, text=True, timeout=15)
    assert simulated.returncode == 0 and 'PASS AXIS' in simulated.stdout, simulated.stdout + simulated.stderr


def test_axis_handshake_scoreboard_rejects_ignored_backpressure(axis_pair, tmp_path):
    document, library = axis_pair
    generated = []
    for name, text in generate_files(document, library).items():
        target = tmp_path / name
        target.write_text(text, encoding='utf-8')
        generated.append(str(target))
    bench = ROOT / 'tests/fixtures/interfaces/axis_pair_tb.sv'
    original = bench.read_bytes()
    faulty = original.replace(b'.out_ready(out_ready)', b".out_ready(1'b1)")
    assert faulty != original
    faulty_path = tmp_path / 'faulty_tb.sv'
    faulty_path.write_bytes(faulty)
    compiled = subprocess.run([shutil.which('iverilog'), '-g2012', '-s', 'tb', '-o', str(tmp_path / 'simulation'),
        *generated, str(library[0].base_dir / library[0].source.path), str(faulty_path)], capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stderr
    simulated = subprocess.run([shutil.which('vvp'), str(tmp_path / 'simulation')], capture_output=True, text=True, timeout=15)
    assert simulated.returncode != 0
    assert any(reason in simulated.stdout for reason in ('backpressure', 'reordered', 'duplicated', 'lost'))
    assert bench.read_bytes() == original


def test_axis_connection_lowers_ready_in_reverse_without_persisting_nets(axis_pair):
    document, library = axis_pair
    before = deepcopy(document)
    result = inspect_design(document, library)
    assert result['valid'], result['diagnostics']
    signals = result['bus_interfaces']['connections'][0]['signals']
    assert signals['tdata']['source'] == {'inst': 'first', 'port': 'm_data'}
    assert signals['tready']['source'] == {'inst': 'second', 'port': 's_ready'}
    assert signals['tready']['sink'] == {'inst': 'first', 'port': 'm_ready'}
    assert '__bd_if_link__tdata' in result['files']['axis_pair.v']
    assert document == before


@pytest.mark.parametrize('case,code', [('role', 'E202'), ('width', 'E204'), ('overlap', 'E205'), ('unknown', 'E203')])
def test_axis_connection_reports_structured_domain_errors(axis_pair, case, code):
    document, library = axis_pair
    if case == 'role':
        document['interface_connections'][0]['to']['interface'] = 'm_axis'
    elif case == 'width':
        document['instances'][1]['params']['WIDTH'] = 16
    elif case == 'overlap':
        document['nets'].append({'name': 'conflict', 'endpoints': [{'const': "4'd0"}, {'inst': 'second', 'port': 's_data', 'slice': [3, 0]}]})
    else:
        document['interface_connections'][0]['to']['interface'] = 'invented'
    result = inspect_design(document, library)
    assert not result['valid'] and not result['files']
    finding = next(item for item in result['diagnostics'] if item['code'] == code)
    assert finding['location']['connection'] == 'link'
    assert finding['params']


def test_axis_external_interface_role_is_mirrored_inside_the_design(axis_pair):
    document, library = axis_pair
    document['interfaces'] = [{'name': 'output_stream', 'protocol': 'axi-stream', 'definition_version': '1.0.0',
        'profile': 'ready-valid', 'mode': 'master', 'parameters': {'DATA_WIDTH': '8'}, 'confirmed': True,
        'signals': {'tdata': 'out_data', 'tvalid': 'out_valid', 'tready': 'out_ready'}}]
    document['nets'] = [net for net in document['nets'] if not net['name'].startswith('out_')]
    document['interface_connections'].append({'name': 'output_link', 'from': {'inst': 'second', 'interface': 'm_axis'},
                                             'to': {'ext_interface': 'output_stream'}})
    result = inspect_design(document, library)
    assert result['valid'], result['diagnostics']
    output = next(item for item in result['bus_interfaces']['connections'] if item['name'] == 'output_link')
    assert output['signals']['tready']['source'] == {'ext': 'out_ready'}


@pytest.mark.parametrize('unrelated_missing_input', [False, True])
def test_axis_optional_fix_requires_confirmation_and_materializes_the_connection(axis_pair, unrelated_missing_input):
    document, library = axis_pair
    document['ports']['out_last'] = {'direction': 'output'}
    document['interfaces'] = [{'name': 'output_stream', 'protocol': 'axi-stream', 'definition_version': '1.0.0',
        'profile': 'ready-valid', 'mode': 'master', 'parameters': {'DATA_WIDTH': '8'}, 'confirmed': True,
        'signals': {'tdata': 'out_data', 'tvalid': 'out_valid', 'tready': 'out_ready', 'tlast': 'out_last'}}]
    document['nets'] = [net for net in document['nets'] if not net['name'].startswith('out_')]
    document['interface_connections'].append({'name': 'output_link', 'from': {'inst': 'second', 'interface': 'm_axis'},
                                             'to': {'ext_interface': 'output_stream'}})
    if unrelated_missing_input:
        document['nets'] = [net for net in document['nets'] if net['name'] != 'clk_net']
    before = deepcopy(document)
    result = inspect_design(document, library)
    diagnostic = next(item for item in result['diagnostics'] if item['code'] == 'E207')
    assert diagnostic['fix']['kind'] == 'materialize_interface'
    assert diagnostic['fix']['requires_confirmation'] is True
    with pytest.raises(DesignFormatError):
        apply_fix(document, library, diagnostic)
    changed = apply_fix(document, library, diagnostic, confirmed=True)
    assert document == before
    assert [item['name'] for item in changed['interface_connections']] == ['link']
    assert any({'const': "1'b0"} in net['endpoints'] and {'ext': 'out_last'} in net['endpoints'] for net in changed['nets'])
    checked = inspect_design(changed, library)
    assert checked['valid'] is not unrelated_missing_input
    if unrelated_missing_input:
        assert any(item['code'] == 'E003' and item['location'].get('port') == 'clk' for item in result['diagnostics'])
    forged = deepcopy(diagnostic)
    forged['fix']['connection'] = 'link'
    with pytest.raises(DesignFormatError):
        apply_fix(document, library, forged, confirmed=True)


def test_axis_duplicate_external_names_are_not_silently_selected(axis_pair):
    document, library = axis_pair
    declaration = {'name': 'output_stream', 'protocol': 'axi-stream', 'definition_version': '1.0.0',
        'profile': 'ready-valid', 'mode': 'master', 'parameters': {'DATA_WIDTH': '8'}, 'confirmed': True,
        'signals': {'tdata': 'out_data', 'tvalid': 'out_valid', 'tready': 'out_ready'}}
    document['interfaces'] = [declaration, deepcopy(declaration)]
    result = inspect_design(document, library)
    assert not result['valid']
    assert any(item['code'] == 'E208' for item in result['diagnostics'])


def test_axis_source_map_locates_each_generated_member(axis_pair):
    document, library = axis_pair
    artifacts = generate_artifacts(document, library)
    assert artifacts['source_map']['schema_version'] == 2
    records = artifacts['source_map']['files']['axis_pair.v']['ranges']
    assert {item['location']['signal'] for item in records if item['location'].get('connection') == 'link'} == {'tdata', 'tvalid', 'tready'}
    text = artifacts['files']['axis_pair.v']
    assert 'schema_version: 5' in text
    for item in records:
        if item['location'].get('connection') == 'link':
            line = text.splitlines()[item['start_line'] - 1]
            assert f"__bd_if_link__{item['location']['signal']}" in line


def test_axis_generated_name_collision_is_an_explicit_error(axis_pair):
    document, library = axis_pair
    document['ports']['__bd_if_link__tdata'] = {'direction': 'input'}
    result = inspect_design(document, library)
    assert not result['valid']
    assert any(item['code'] == 'E208' and item['params']['generated_name'] == '__bd_if_link__tdata' for item in result['diagnostics'])


def test_axis_drag_direction_does_not_change_generated_electrical_direction(axis_pair):
    document, library = axis_pair
    expected = generate_files(document, library)
    connection = document['interface_connections'][0]
    connection['from'], connection['to'] = connection['to'], connection['from']
    assert generate_files(document, library) == expected


def test_axis_confirmed_strb_fix_follows_keep_without_duplicating_driver_nets(axis_pair):
    document, library = axis_pair
    for prefix, mode, forward in [('extra', 'slave', 'input'), ('result', 'master', 'output')]:
        signals = {'tdata': f'{prefix}_data', 'tvalid': f'{prefix}_valid', 'tready': f'{prefix}_ready', 'tkeep': f'{prefix}_keep'}
        if mode == 'master':
            signals['tstrb'] = f'{prefix}_strb'
        for signal, name in signals.items():
            direction = ('output' if forward == 'input' else 'input') if signal == 'tready' else forward
            document['ports'][name] = {'direction': direction, **({'range': [7, 0]} if signal == 'tdata' else {})}
        document['interfaces'].append({'name': prefix, 'protocol': 'axi-stream', 'definition_version': '1.0.0',
            'profile': 'ready-valid', 'mode': mode, 'parameters': {'DATA_WIDTH': '8'}, 'signals': signals, 'confirmed': True})
    document['interface_connections'].append({'name': 'extras', 'from': {'ext_interface': 'extra'}, 'to': {'ext_interface': 'result'}})
    result = inspect_design(document, library)
    diagnostic = next(item for item in result['diagnostics'] if item['code'] == 'E207')
    assert diagnostic['fix']['bindings'][0]['source'] == {'ext': 'extra_keep'}
    changed = apply_fix(document, library, diagnostic, confirmed=True)
    containing = [net for net in changed['nets'] if {'ext': 'extra_keep'} in net['endpoints']]
    assert len(containing) == 1
    assert {'ext': 'result_keep'} in containing[0]['endpoints'] and {'ext': 'result_strb'} in containing[0]['endpoints']
    assert inspect_design(changed, library)['valid']


def test_axis_connections_inside_child_definitions_are_expanded_locally(axis_pair):
    child, library = axis_pair
    child.pop('subdesigns')
    child['name'] = 'chain'
    document = {'schema_version': 5, 'name': 'parent_axis', 'ports': deepcopy(child['ports']),
        'instances': [{'name': 'group', 'ip': {'id': 'chain', 'version': '1.0.0'}}],
        'nets': [{'name': f'{name}_net', 'endpoints': [{'ext': name}, {'inst': 'group', 'port': name}]} for name in child['ports']],
        'subdesigns': {'chain': child}, 'interfaces': [], 'interface_connections': []}
    result = inspect_design(document, library)
    assert result['valid'], result['diagnostics']
    assert '__bd_if_link__tready' in result['files']['chain.v']
    assert document['subdesigns']['chain']['interface_connections'][0]['name'] == 'link'


def test_axis_workspace_roundtrip_keeps_only_authoritative_connections(axis_pair, tmp_path):
    document, library = axis_pair
    metadata = library[0].to_dict()
    metadata['source']['path'] = 'bd_stream_slice.v'
    shutil.copyfile(library[0].base_dir / library[0].source.path, tmp_path / 'bd_stream_slice.v')
    document['project_ips'] = [metadata]
    workspace = Workspace(tmp_path, 'designs/axis_pair.json')
    inspected = workspace.semantic_inspect(document, '.')
    assert inspected['valid'], inspected['diagnostics']
    saved = workspace.save({'design': document, 'base_dir': '.', 'path': 'designs/axis_pair.json'})
    assert saved['inspection']['valid'], saved['inspection']['diagnostics']
    restored = saved['design']
    assert restored['schema_version'] == 5
    assert restored['interface_connections'] == document['interface_connections']
    assert not any(net['name'].startswith('__bd_if_') for net in restored['nets'])
    assert '__bd_if_link__tready' in saved['inspection']['canvas']['nets']
    before = (tmp_path / 'designs/axis_pair.json').read_bytes()
    workspace.load('designs/axis_pair.json')
    assert (tmp_path / 'designs/axis_pair.json').read_bytes() == before
    embedded_path = tmp_path / 'designs/embedded.json'
    embedded_path.write_text(json.dumps({**restored, 'layout': saved['layout']}), encoding='utf-8')
    embedded_bytes = embedded_path.read_bytes()
    embedded = workspace.load('designs/embedded.json')
    assert embedded['design']['schema_version'] == 5 and embedded['inspection']['valid']
    assert embedded_path.read_bytes() == embedded_bytes


def test_axis_workspace_fix_requires_explicit_confirmation(axis_pair, tmp_path):
    document, library = axis_pair
    metadata = library[0].to_dict()
    metadata['source']['path'] = 'bd_stream_slice.v'
    shutil.copyfile(library[0].base_dir / library[0].source.path, tmp_path / 'bd_stream_slice.v')
    document['project_ips'] = [metadata]
    document['ports']['out_last'] = {'direction': 'output'}
    document['interfaces'] = [{'name': 'output_stream', 'protocol': 'axi-stream', 'definition_version': '1.0.0',
        'profile': 'ready-valid', 'mode': 'master', 'parameters': {'DATA_WIDTH': '8'}, 'confirmed': True,
        'signals': {'tdata': 'out_data', 'tvalid': 'out_valid', 'tready': 'out_ready', 'tlast': 'out_last'}}]
    document['nets'] = [net for net in document['nets'] if not net['name'].startswith('out_')]
    document['interface_connections'].append({'name': 'output_link', 'from': {'inst': 'second', 'interface': 'm_axis'},
                                             'to': {'ext_interface': 'output_stream'}})
    workspace = Workspace(tmp_path, 'unused.json')
    inspected = workspace.semantic_inspect(document, '.')
    diagnostic = next(item for item in inspected['diagnostics'] if item['code'] == 'E207')
    payload = {'design': document, 'base_dir': '.', 'diagnostic': diagnostic}
    with pytest.raises(DesignFormatError):
        workspace.semantic_fix(payload)
    fixed = workspace.semantic_fix({**payload, 'confirmed': True})
    assert fixed['valid']
    assert [item['name'] for item in fixed['document']['interface_connections']] == ['link']
    assert len(document['interface_connections']) == 2
    assert not (tmp_path / 'designs').exists()


if __name__ == '__main__':
    if sys.argv[1:] == ['--freeze-axis']:
        destination = ROOT / 'examples/interfaces/axis_pair.json'
        frozen = Path(__file__).parent / 'golden/axis-pair.json'
        if destination.exists() or frozen.exists():
            raise SystemExit('Refusing to overwrite the interface example or its independent golden.')
        document, library = axis_pair_data()
        expected = generate_files(axis_scalar_reference(document), library)
        frozen.write_bytes((json.dumps({name: text.replace('schema_version: 4', 'schema_version: 5', 1) for name, text in expected.items()}, indent=2) + '\n').encode())
        metadata = library[0].to_dict()
        metadata['source']['path'] = '../../ip_library/builtin/bd_stream_slice/1.0.0/src/bd_stream_slice.v'
        document['project_ips'] = [metadata]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((json.dumps(document, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        print('Created project-local v2 profile and a golden from handwritten scalar connections.')
        raise SystemExit(0)
    if sys.argv[1:] != ['--freeze-v4'] or GOLDEN.exists():
        raise SystemExit('Only --freeze-v4 is supported, and an existing golden must never be overwritten.')
    result = {}
    for case in CASES:
        document, library = baseline(case)
        result[case] = {mode: outputs(document, library, mode) for mode in ('legacy', 'v', 'sv')}
    GOLDEN.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print('Frozen three v4 designs in three output modes; no existing golden changed.')