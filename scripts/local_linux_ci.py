import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
from urllib.parse import urlparse
import zipfile


class SetupError(ValueError):
    pass


def digest(path):
    checksum = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def external_prefix(repo, prefix):
    repo, prefix = Path(repo).resolve(), Path(prefix).resolve()
    if prefix == repo or prefix in repo.parents or repo in prefix.parents:
        raise SetupError('Tool prefix and checkout must be disjoint')
    return repo, prefix


def load_manifest(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if set(data) != {'schema_version', 'versions', 'assets'} or data['schema_version'] != 1:
        raise SetupError('Unsupported tool manifest')
    names = set()
    for asset in data['assets']:
        if set(asset) != {'name', 'kind', 'folder', 'url', 'sha256'}:
            raise SetupError('Unknown tool manifest fields')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', asset['name']) or asset['name'] in names:
            raise SetupError('Invalid or duplicate archive name')
        names.add(asset['name'])
        folder = PurePosixPath(asset['folder'])
        if folder.is_absolute() or '..' in folder.parts or not folder.parts:
            raise SetupError('Archive destination escaped the tool prefix')
        source = urlparse(asset['url'])
        if source.scheme != 'https' or source.hostname not in {'nodejs.org', 'github.com', 'cdn.playwright.dev', 'archive.ubuntu.com'} or source.username or source.password:
            raise SetupError('Unexpected archive source')
        if asset['kind'] not in ('tar', 'zip', 'deb') or not re.fullmatch(r'[a-f0-9]{64}', asset['sha256']):
            raise SetupError('Invalid archive kind or checksum')
    return data


def fetch_asset(asset, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / asset['name']
    if not destination.exists():
        temporary = destination.with_suffix(destination.suffix + '.part')
        subprocess.run(['curl', '--fail', '--location', '--show-error', '--connect-timeout', '20', '--max-time', '300',
                        '--output', str(temporary), '--url', asset['url']], check=True)
        if digest(temporary) != asset['sha256']:
            raise SetupError(f"Downloaded checksum mismatch: {asset['name']}")
        temporary.replace(destination)
    if digest(destination) != asset['sha256']:
        raise SetupError(f"Cached checksum mismatch: {asset['name']}")
    return destination


def extract_asset(asset, archive, prefix):
    target = Path(prefix) / asset['folder']
    if not target.resolve().is_relative_to(Path(prefix).resolve()):
        raise SetupError('Installation target escaped the tool prefix')
    target.mkdir(parents=True, exist_ok=True)
    if asset['kind'] == 'tar':
        subprocess.run(['tar', '-xf', str(archive), '--strip-components=1', '-C', str(target)], check=True)
    elif asset['kind'] == 'deb':
        subprocess.run(['dpkg-deb', '-x', str(archive), str(target)], check=True)
    else:
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.infolist():
                destination = (target / member.filename).resolve()
                mode = member.external_attr >> 16
                if not destination.is_relative_to(target.resolve()) or stat.S_ISLNK(mode):
                    raise SetupError('Unsafe browser archive entry')
            for member in zipped.infolist():
                destination = Path(zipped.extract(member, target))
                mode = (member.external_attr >> 16) & 0o777
                if mode:
                    destination.chmod(mode)
    return target


def tool_environment(prefix):
    prefix = Path(prefix).resolve()
    environment = dict(os.environ)
    if environment.get('NODE_TLS_REJECT_UNAUTHORIZED') == '0':
        raise SetupError('TLS verification must remain enabled')
    environment.update({
        'PATH': os.pathsep.join(str(prefix / folder) for folder in ('node/bin', 'venv/bin', 'oss-cad-suite/bin')) + os.pathsep + '/usr/local/bin:/usr/bin:/bin',
        'BD_PYTHON': str(prefix / 'venv/bin/python3'),
        'BD_VERILATOR': str(prefix / 'oss-cad-suite/bin/verilator'),
        'VERILATOR_ROOT': str(prefix / 'oss-cad-suite/share/verilator'),
        'BD_YOSYS': str(prefix / 'venv/bin/yowasp-yosys'),
        'PLAYWRIGHT_BROWSERS_PATH': str(prefix / 'browsers'),
        'LD_LIBRARY_PATH': str(prefix / 'browser-libs/usr/lib/x86_64-linux-gnu'),
        'NODE_EXTRA_CA_CERTS': environment.get('NODE_EXTRA_CA_CERTS', '/etc/ssl/certs/ca-certificates.crt'),
        'npm_config_cache': str(prefix / 'npm-cache'),
        'PIP_DISABLE_PIP_VERSION_CHECK': '1',
    })
    return environment


def link_dependencies(repo, prefix):
    link = Path(repo) / 'web/node_modules'
    target = Path(prefix) / 'frontend/node_modules'
    if link.is_symlink():
        if link.resolve() != target.resolve():
            raise SetupError('Existing dependency link points elsewhere')
    elif link.exists():
        raise SetupError('Use a clean checkout; existing node_modules is not overwritten')
    else:
        link.symlink_to(target, target_is_directory=True)


def run(arguments, *, cwd, environment, capture=False):
    print('> ' + ' '.join(map(str, arguments)), flush=True)
    return subprocess.run(list(map(str, arguments)), cwd=cwd, env=environment, check=True, text=True, capture_output=capture)


def verify_versions(repo, prefix, manifest, environment):
    versions = manifest['versions']
    commands = {
        'node': ([prefix / 'node/bin/node', '--version'], f"v{versions['node']}"),
        'python': ([prefix / 'venv/bin/python3', '--version'], f"Python {versions['python']}"),
        'playwright': ([prefix / 'node/bin/node', repo / 'web/node_modules/playwright/cli.js', '--version'], f"Version {versions['playwright']}"),
        'chromium': ([prefix / 'browsers/chromium_headless_shell-1208/chrome-headless-shell-linux64/chrome-headless-shell', '--version'], f"Google Chrome for Testing {versions['chromium']}"),
    }
    observed = {}
    for name, (command, expected) in commands.items():
        observed[name] = run(command, cwd=repo, environment=environment, capture=True).stdout.strip()
        if observed[name] != expected:
            raise SetupError(f'Runtime version mismatch: {name}')
    for name, command, expected in (
        ('verilator', [environment['BD_VERILATOR'], '--version'], 'Verilator 5.055 devel rev v5.054-302-g2d6aba6ed'),
        ('yosys', [environment['BD_YOSYS'], '-V'], 'Yosys 0.70 (git sha1 28ba3cb92,'),
    ):
        observed[name] = run(command, cwd=repo, environment=environment, capture=True).stdout.strip()
        if not observed[name].startswith(expected):
            raise SetupError(f'HDL version mismatch: {name}')
    return observed


def setup(repo, prefix):
    repo, prefix = external_prefix(repo, prefix)
    if sys.platform != 'linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
        raise SetupError('This bootstrap requires Linux x86_64')
    if os.geteuid() == 0:
        raise SetupError('Run as an ordinary user without sudo')
    for program in ('curl', 'tar', 'dpkg-deb'):
        if shutil.which(program) is None:
            raise SetupError(f'Missing bootstrap prerequisite: {program}')
    manifest_path = repo / 'scripts/linux-ci-tools.json'
    manifest = load_manifest(manifest_path)
    fingerprint = {name: digest(repo / name) for name in ('scripts/linux-ci-tools.json', 'requirements-linux-ci.lock', 'web/package-lock.json')}
    state_path = prefix / 'setup-state.json'
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.is_file() else None
    if state is not None and state.get('fingerprint') != fingerprint:
        raise SetupError('Toolchain lock changed; choose a new external prefix')
    if state is None and prefix.exists() and any(prefix.iterdir()):
        raise SetupError('Refusing to overwrite a nonempty unowned tool prefix')
    modules = repo / 'web/node_modules'
    if modules.exists() and not modules.is_symlink():
        raise SetupError('Use a clean checkout without an existing node_modules directory')
    prefix.mkdir(parents=True, exist_ok=True, mode=0o700)
    state = state or {'schema_version': 1, 'fingerprint': fingerprint, 'installed': False}
    state_path.write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
    archives = {asset['name']: fetch_asset(asset, prefix / 'downloads') for asset in manifest['assets']}
    environment = tool_environment(prefix)
    if not state['installed']:
        for asset in manifest['assets']:
            extract_asset(asset, archives[asset['name']], prefix)
        run([prefix / 'python/bin/python3.14', '-m', 'venv', prefix / 'venv'], cwd=repo, environment=environment)
        run([environment['BD_PYTHON'], '-m', 'pip', '--isolated', 'install', '--require-hashes', '--only-binary=:all:', '--no-cache-dir',
             '--index-url', 'https://pypi.org/simple', '--cert', environment['NODE_EXTRA_CA_CERTS'], '-r', repo / 'requirements-linux-ci.lock'],
            cwd=repo, environment=environment)
        frontend = prefix / 'frontend'
        frontend.mkdir(exist_ok=True)
        for name in ('package.json', 'package-lock.json'):
            shutil.copyfile(repo / 'web' / name, frontend / name)
        run([prefix / 'node/bin/npm', '--prefix', frontend, 'ci'], cwd=repo, environment=environment)
        link_dependencies(repo, prefix)
        state['installed'] = True
        state_path.write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
    link_dependencies(repo, prefix)
    observed = verify_versions(repo, prefix, manifest, environment)
    report = {'schema_version': 1, 'repo': str(repo), 'prefix': str(prefix), 'versions': observed, 'fingerprint': fingerprint,
              'archive_sha256': {name: digest(archive) for name, archive in archives.items()}, 'sudo_used': False,
              'dependencies_outside_checkout': modules.resolve().is_relative_to(prefix), 'real_model_called': False}
    (prefix / 'installation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)
    return repo, prefix, environment


def main(argv=None):
    parser = argparse.ArgumentParser(description='Pinned user-only Linux CI bootstrap and verification')
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--mode', choices=('setup', 'target', 'check', 'verify'), default='verify')
    arguments = parser.parse_args(argv)
    repo, prefix = external_prefix(arguments.repo, arguments.prefix)
    marker = prefix / f'{arguments.mode}-passed.json'
    marker.unlink(missing_ok=True)
    repo, prefix, environment = setup(arguments.repo, arguments.prefix)
    if arguments.mode in ('target', 'verify'):
        run([prefix / 'node/bin/npm', '--prefix', repo / 'web', 'run', 'build'], cwd=repo, environment=environment)
        run([prefix / 'node/bin/node', repo / 'web/node_modules/playwright/cli.js', 'test', '--config', repo / 'web/playwright.config.js',
             '--grep', 'AXI-Stream hierarchy confirms', '--repeat-each', '10', '--workers', '1'], cwd=repo, environment=environment)
    if arguments.mode in ('check', 'verify'):
        run([environment['BD_PYTHON'], '-u', repo / 'scripts/check.py'], cwd=repo, environment=environment)
    marker.write_text(json.dumps({'mode': arguments.mode, 'passed': True}) + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (SetupError, OSError, subprocess.CalledProcessError) as failure:
        print(f'Linux CI setup/check failed: {failure}', file=sys.stderr)
        raise SystemExit(1) from failure