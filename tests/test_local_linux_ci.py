from copy import deepcopy
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from scripts.local_linux_ci import SetupError, external_prefix, extract_asset, fetch_asset, link_dependencies, load_manifest, tool_environment
from scripts import local_linux_ci


ROOT = Path(__file__).resolve().parents[1]


def test_agent_rules_match_repository_original_and_linux_entry_exists():
    plan = (ROOT / 'IMPLEMENTATION_PLAN.md').read_text(encoding='utf-8')
    start = plan.index('## 0. 执行规则')
    original = plan[start:plan.index('\n---', start)].strip()
    assert original in (ROOT / 'AGENTS.md').read_text(encoding='utf-8')
    assert (ROOT / 'docs/local-linux-ci.md').is_file()
    lock = (ROOT / 'requirements-linux-ci.lock').read_text(encoding='utf-8').splitlines()
    assert lock and all('==' in line and ' --hash=sha256:' in line for line in lock)


def test_linux_tool_manifest_is_fixed_and_external_prefix_is_required(tmp_path):
    manifest = load_manifest(ROOT / 'scripts/linux-ci-tools.json')
    assert manifest['versions']['node'] == '24.22.3'
    assert manifest['versions']['chromium'] == '145.0.7632.6'
    assert len(manifest['assets']) == 9
    repo, prefix = external_prefix(tmp_path / 'repo', tmp_path / 'tools')
    assert repo != prefix
    for invalid in (repo, repo / 'tools', repo.parent):
        with pytest.raises(SetupError):
            external_prefix(repo, invalid)
    malicious = deepcopy(manifest)
    malicious['assets'][0]['folder'] = '../outside'
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(malicious), encoding='utf-8')
    with pytest.raises(SetupError):
        load_manifest(path)


def test_linux_download_cache_is_reverified_without_network(tmp_path, monkeypatch):
    content = b'verified archive'
    asset = {'name': 'archive', 'url': 'https://nodejs.org/unused', 'sha256': hashlib.sha256(content).hexdigest()}
    (tmp_path / 'archive').write_bytes(content)
    def forbidden(*args, **kwargs):
        raise AssertionError('The unit test must not access the network')
    monkeypatch.setattr('scripts.local_linux_ci.subprocess.run', forbidden)
    assert fetch_asset(asset, tmp_path).read_bytes() == content
    (tmp_path / 'archive').write_bytes(b'changed')
    with pytest.raises(SetupError, match='Cached checksum mismatch'):
        fetch_asset(asset, tmp_path)
    assert (tmp_path / 'archive').read_bytes() == b'changed'


def test_linux_browser_archive_rejects_path_escape_before_extracting(tmp_path):
    archive = tmp_path / 'unsafe.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('safe', b'first')
        output.writestr('../escape', b'bad')
    with pytest.raises(SetupError, match='Unsafe browser archive'):
        extract_asset({'kind': 'zip', 'folder': 'browser'}, archive, tmp_path / 'tools')
    assert not (tmp_path / 'tools/browser/safe').exists()
    assert not (tmp_path / 'tools/escape').exists()


def test_linux_environment_keeps_suite_libc_out_of_global_library_path(tmp_path, monkeypatch):
    environment = tool_environment(tmp_path / 'tools')
    assert 'oss-cad-suite' not in environment['LD_LIBRARY_PATH']
    assert environment['BD_PYTHON'].startswith(str(tmp_path / 'tools'))
    assert environment['BD_VERILATOR'].endswith('verilator')
    monkeypatch.setenv('NODE_TLS_REJECT_UNAUTHORIZED', '0')
    with pytest.raises(SetupError, match='TLS verification'):
        tool_environment(tmp_path / 'tools')


def test_linux_setup_does_not_replace_existing_checkout_dependencies(tmp_path):
    modules = tmp_path / 'repo/web/node_modules'
    modules.mkdir(parents=True)
    protected = modules / 'user-file'
    protected.write_bytes(b'unchanged')
    with pytest.raises(SetupError, match='not overwritten'):
        link_dependencies(tmp_path / 'repo', tmp_path / 'tools')
    assert protected.read_bytes() == b'unchanged'


def test_linux_failed_recheck_cannot_retain_success_marker(tmp_path, monkeypatch):
    repo, prefix = tmp_path / 'repo', tmp_path / 'tools'
    prefix.mkdir()
    marker = prefix / 'verify-passed.json'
    marker.write_text('{"passed": true}', encoding='utf-8')
    monkeypatch.setattr(local_linux_ci, 'setup', lambda *args: (repo, prefix, {}))
    def failed(*args, **kwargs):
        raise SetupError('Controlled check failure')
    monkeypatch.setattr(local_linux_ci, 'run', failed)
    with pytest.raises(SetupError, match='Controlled check failure'):
        local_linux_ci.main(['--repo', str(repo), '--prefix', str(prefix), '--mode', 'verify'])
    assert not marker.exists()