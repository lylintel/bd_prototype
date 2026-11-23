from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

from bdgui import Workspace
from bdsemantic import prepare
from core.design import DesignFormatError, check_document, load_document, migrate
from core.generation import generate_files
from core.persistence import canonical_document, write_project
from core.semantic import inspect_design


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


if __name__ == '__main__':
    if sys.argv[1:] != ['--freeze-v4'] or GOLDEN.exists():
        raise SystemExit('Only --freeze-v4 is supported, and an existing golden must never be overwritten.')
    result = {}
    for case in CASES:
        document, library = baseline(case)
        result[case] = {mode: outputs(document, library, mode) for mode in ('legacy', 'v', 'sv')}
    GOLDEN.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print('Frozen three v4 designs in three output modes; no existing golden changed.')