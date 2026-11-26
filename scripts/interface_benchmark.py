import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter

from bdgui import Workspace
from bdip import IpMetadata
from core.design import load_document
from core.generation import generate_artifacts
from core.interfaces import expand_interfaces
from core.persistence import canonical_document


ROOT = Path(__file__).resolve().parents[1]


def write_pair(directory, count):
    if type(count) is not int or not 2 <= count <= 2000:
        raise ValueError('Expected 2..2000 instances')
    directory = Path(directory)
    example_path = ROOT / 'examples/interfaces/axis_pair.json'
    example = json.loads(example_path.read_text(encoding='utf-8'))
    metadata = deepcopy(example['project_ips'][0])
    source = (example_path.parent / metadata['source']['path']).read_bytes()
    if hashlib.sha256(source).hexdigest() != metadata['source']['sha256']:
        raise ValueError('Benchmark source hash mismatch')
    metadata['source']['path'] = 'bd_stream_slice.v'
    instances = [{'name': f'unit_{index}', 'ip': {'id': metadata['id'], 'version': metadata['version']}, 'params': {'WIDTH': 8}}
                 for index in range(count)]
    common_nets = [{'name': f'{name}_net', 'endpoints': [{'ext': name}, *[{'inst': instance['name'], 'port': name} for instance in instances]]}
                   for name in ('clk', 'rst')]
    for external, instance, port in [('in_data', 'unit_0', 's_data'), ('in_valid', 'unit_0', 's_valid'), ('in_ready', 'unit_0', 's_ready'),
                                    ('out_data', f'unit_{count - 1}', 'm_data'), ('out_valid', f'unit_{count - 1}', 'm_valid'), ('out_ready', f'unit_{count - 1}', 'm_ready')]:
        common_nets.append({'name': f'{external}_net', 'endpoints': [{'ext': external}, {'inst': instance, 'port': port}]})
    signal = {'schema_version': 4, 'name': 'axis_performance', 'ports': deepcopy(example['ports']), 'instances': instances,
              'nets': deepcopy(common_nets), 'subdesigns': {}, 'project_ips': [metadata]}
    interface = {**deepcopy(signal), 'schema_version': 5, 'interfaces': [], 'interface_connections': []}
    for index in range(count - 1):
        source_name, target_name = f'unit_{index}', f'unit_{index + 1}'
        name = f'link_{index}'
        interface['interface_connections'].append({'name': name, 'from': {'inst': source_name, 'interface': 'm_axis'},
                                                   'to': {'inst': target_name, 'interface': 's_axis'}})
        signal['nets'].extend([
            {'name': f'__bd_if_{name}__tdata', 'endpoints': [{'inst': source_name, 'port': 'm_data'}, {'inst': target_name, 'port': 's_data'}]},
            {'name': f'__bd_if_{name}__tvalid', 'endpoints': [{'inst': source_name, 'port': 'm_valid'}, {'inst': target_name, 'port': 's_valid'}]},
            {'name': f'__bd_if_{name}__tready', 'endpoints': [{'inst': target_name, 'port': 's_ready'}, {'inst': source_name, 'port': 'm_ready'}]},
        ])
    library = (IpMetadata.from_dict(metadata),)
    expanded = expand_interfaces(interface, library)
    if expanded['diagnostics'] or canonical_document(expanded['document']) != canonical_document(signal):
        raise ValueError('Paired fixtures are not electrically equivalent')
    columns = math.ceil(math.sqrt(count))
    layout = {'nodes': {instance['name']: {'x': 280 + index % columns * 360, 'y': 80 + index // columns * 330}
                        for index, instance in enumerate(instances)}, 'viewport': {'x': 0, 'y': 0, 'zoom': 0.75}}
    for ordinal, name in enumerate(example['ports']):
        layout['nodes'][f'@{name}'] = {'x': 20, 'y': 80 + ordinal * 80}
    sizes = {}
    for variant, document in [('signal', signal), ('interface', interface)]:
        destination = directory / variant
        destination.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode('utf-8') + b'\n'
        if len(encoded) > 2 * 1024 * 1024:
            raise ValueError('Fixture exceeds the existing 2 MiB document limit')
        (destination / 'design.json').write_bytes(encoded)
        (destination / 'design.layout.json').write_text(json.dumps(layout, separators=(',', ':')) + '\n', encoding='utf-8')
        (destination / 'bd_stream_slice.v').write_bytes(source)
        sizes[variant] = {'document_bytes': len(encoded), 'document_sha256': hashlib.sha256(encoded).hexdigest(),
                          'raw_nets': len(document['nets'])}
    result = {'instances': count, 'expanded_nets': len(signal['nets']), 'interface_connections': count - 1,
              'derived_signal_nets': 3 * (count - 1), 'source_sha256': metadata['source']['sha256'], 'variants': sizes,
              'equivalence': 'complete canonical physical document equality; independent scalar DATA/VALID/READY connections'}
    (directory / 'pair.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def retained_size(value):
    visited = set()

    def size(item):
        if id(item) in visited:
            return 0
        visited.add(id(item))
        total = sys.getsizeof(item)
        if isinstance(item, dict):
            total += sum(size(key) + size(child) for key, child in item.items())
        elif isinstance(item, (list, tuple)):
            total += sum(size(child) for child in item)
        return total

    return size(value)


def measure_pair(directory, *, repetitions=3, first='signal', progress=False):
    if type(repetitions) is not int or not 1 <= repetitions <= 11 or first not in ('signal', 'interface'):
        raise ValueError('Invalid paired measurement arguments')
    directory = Path(directory)
    raw = {variant: (directory / variant / 'design.json').read_text(encoding='utf-8') for variant in ('signal', 'interface')}
    documents = {variant: load_document(text) for variant, text in raw.items()}
    libraries = {variant: tuple(IpMetadata.from_dict(item) for item in document['project_ips']) for variant, document in documents.items()}
    workspaces = {variant: Workspace(directory / variant, 'design.json') for variant in documents}
    operations = {'parse_ms': lambda variant: load_document(raw[variant]),
                  'inspect_ms': lambda variant: workspaces[variant].semantic_inspect(documents[variant], '.'),
                  'generate_ms': lambda variant: generate_artifacts(documents[variant], libraries[variant])}
    measurements, outputs = {}, {}
    order = [first, 'interface' if first == 'signal' else 'signal']
    for phase, operation in operations.items():
        values = {variant: [] for variant in documents}
        sequence = []
        for variant in order:
            operation(variant)
        for iteration in range(repetitions):
            for variant in order if iteration % 2 == 0 else list(reversed(order)):
                started = perf_counter()
                value = operation(variant)
                elapsed = (perf_counter() - started) * 1000
                if phase == 'inspect_ms' and not value['valid']:
                    raise ValueError(value['diagnostics'])
                if phase == 'generate_ms':
                    outputs[variant] = value
                values[variant].append(elapsed)
                sequence.append({'variant': variant, 'milliseconds': elapsed})
                if progress:
                    print(json.dumps({'phase': phase, 'variant': variant, 'iteration': iteration + 1, 'milliseconds': elapsed}), file=sys.stderr, flush=True)
        medians = {variant: statistics.median(samples) for variant, samples in values.items()}
        measurements[phase] = {**medians, 'ratio': medians['interface'] / medians['signal'], 'sequence': sequence}
    normalized = {name: text.replace('schema_version: 5', 'schema_version: 4', 1) for name, text in outputs['interface']['files'].items()}
    if normalized != outputs['signal']['files']:
        raise ValueError('Paired generated HDL differs beyond its schema header')
    expanded = expand_interfaces(documents['interface'], libraries['interface'])
    if expanded['diagnostics'] or canonical_document(expanded['document']) != canonical_document(documents['signal']):
        raise ValueError('Paired document changed during measurement')
    memory = {variant: {'raw_nets_bytes': retained_size(document['nets']),
                       'source_map_bytes': len(json.dumps(outputs[variant]['source_map'], separators=(',', ':')).encode('utf-8'))}
              for variant, document in documents.items()}
    memory['interface']['expanded_nets_bytes'] = retained_size(expanded['document']['nets'])
    memory['interface']['derived_nets_bytes'] = retained_size([net for net in expanded['document']['nets'] if net['name'] in expanded['origins'][documents['interface']['name']]])
    return {'python': platform.python_version(), 'repetitions': repetitions, 'warmups_per_phase_variant': 1, 'first': first,
            'metrics': measurements, 'memory': memory, 'physical_equivalence': True, 'hdl_equivalence_except_schema_header': True,
            'memory_method': 'sys.getsizeof of reachable net objects with shared identities counted once; not process RSS',
            'timing_method': 'same process, one warmup then alternating variant order per phase; medians; source hashes rechecked by workspace inspection'}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Create electrically equivalent AXI-Stream performance fixtures')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--instances', type=int, choices=(100, 500, 2000), default=2000)
    parser.add_argument('--measure', action='store_true')
    parser.add_argument('--repetitions', type=int, default=3)
    parser.add_argument('--first', choices=('signal', 'interface'), default='signal')
    args = parser.parse_args(argv)
    result = measure_pair(args.output, repetitions=args.repetitions, first=args.first, progress=True) if args.measure else write_pair(args.output, args.instances)
    print(json.dumps(result))


if __name__ == '__main__':
    main()