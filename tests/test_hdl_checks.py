from pathlib import Path
import subprocess

import pytest

import bdcheck


def test_checks_use_fixed_arguments_and_stage_untrusted_source_names(tmp_path, monkeypatch):
    source = tmp_path / 'source; unexpected.v'
    source.write_text('module leaf; endmodule\n', encoding='utf-8')
    monkeypatch.setattr(bdcheck, 'tool_commands', lambda: {'verilator': ['verilator'], 'yosys': ['yosys']})
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs['timeout'] == 30
        assert not kwargs.get('shell', False)
        assert all('unexpected' not in item for item in command)
        assert Path(kwargs['cwd']).is_dir()
        if command[0] == 'verilator':
            assert '--lint-only' in command and '-Wall' in command
            kwargs['stdout'].write(b'%Warning-UNUSEDSIGNAL: demo.v:4:8: unused signal\n')
        else:
            assert 'read_verilog' in command[-1] and 'hierarchy -check -top demo' in command[-1]
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(bdcheck.subprocess, 'run', run)
    result = bdcheck.run_checks({'demo.v': 'module demo; endmodule\n'}, [source], 'demo')
    assert result['valid']
    assert len(calls) == 2
    assert result['diagnostics'][0]['severity'] == 'warning'
    assert result['diagnostics'][0]['location'] == {'file': 'demo.v', 'line': 4, 'column': 8}
    assert not Path(result['tools'][0]['directory']).exists()


@pytest.mark.parametrize('case', ['missing', 'timeout', 'error'])
def test_check_failures_are_explicit(case, monkeypatch):
    monkeypatch.setattr(bdcheck, 'tool_commands', lambda: {'verilator': None if case == 'missing' else ['verilator'], 'yosys': None})

    def run(command, **kwargs):
        if case == 'timeout':
            raise subprocess.TimeoutExpired(command, 30)
        kwargs['stdout'].write(b'%Error: demo.v:2:1: syntax error\n')
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(bdcheck.subprocess, 'run', run)
    result = bdcheck.run_checks({'demo.v': 'module demo; endmodule\n'}, [], 'demo')
    assert not result['valid']
    assert result['tools'][0]['status'] == {'missing': 'missing', 'timeout': 'timeout', 'error': 'failed'}[case]
    assert result['diagnostics']


@pytest.mark.parametrize('name,top', [('../escape.v', 'demo'), ('demo.v', 'demo; shell command'), ('demo.v', 'module')])
def test_check_identifiers_and_paths_are_validated_before_running(name, top, monkeypatch):
    monkeypatch.setattr(bdcheck, 'tool_commands', lambda: pytest.fail('invalid input must not discover tools'))
    with pytest.raises(ValueError):
        bdcheck.run_checks({name: 'module demo; endmodule\n'}, [], top)


def test_tool_log_overflow_is_not_a_success(monkeypatch):
    monkeypatch.setattr(bdcheck, 'tool_commands', lambda: {'verilator': ['verilator']})

    def run(command, **kwargs):
        kwargs['stdout'].write(b'x' * (bdcheck.MAX_LOG_BYTES + 1))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(bdcheck.subprocess, 'run', run)
    result = bdcheck.run_checks({'demo.v': 'module demo; endmodule\n'}, [], 'demo')
    assert not result['valid']
    assert any(item['code'] == 'HDL_TOOL_LOG_LIMIT' for item in result['diagnostics'])


def test_explicit_missing_tool_does_not_silently_use_another_version(monkeypatch):
    monkeypatch.setenv('BD_VERILATOR', 'missing-selected-verilator')
    monkeypatch.setattr(bdcheck.shutil, 'which', lambda name: '/fallback/verilator_bin' if name == 'verilator_bin' else None)
    assert bdcheck.tool_commands()['verilator'] is None