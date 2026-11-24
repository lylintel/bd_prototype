from pathlib import Path
import subprocess

import pytest

import bdcheck


@pytest.fixture
def pinned_versions(monkeypatch):
    monkeypatch.setattr(bdcheck, 'tool_version', lambda tool, program, directory: ('pinned-test-version', []), raising=False)


def test_version_mismatch_prevents_rtl_execution(monkeypatch):
    monkeypatch.setattr(bdcheck, 'tool_commands', lambda: {'verilator': ['verilator']})
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        kwargs['stdout'].write(b'Verilator 0.001 wrong-version\n')
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(bdcheck.subprocess, 'run', run)
    result = bdcheck.run_checks({'demo.v': 'module demo; endmodule\n'}, [], 'demo')
    assert not result['valid']
    assert calls == [['verilator', '--version']]
    assert result['diagnostics'][0]['code'] == 'HDL_TOOL_VERSION'
    assert '0.001' in result['diagnostics'][0]['params']['detail']


def test_include_outside_workspace_is_rejected_before_tools_without_content(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    outside = tmp_path / 'private.vh'
    outside.write_text('PRIVATE_SENTINEL_DO_NOT_ECHO\n', encoding='utf-8')
    source = workspace / 'unit.v'
    source.write_text(f'`include "{outside.as_posix()}"\nmodule unit; endmodule\n', encoding='utf-8')
    monkeypatch.setattr(bdcheck, 'tool_commands', lambda: pytest.fail('unsafe include must not run tools'))
    result = bdcheck.run_checks({'demo.v': 'module demo; endmodule\n'}, [source], 'demo', workspace_root=workspace)
    assert not result['valid']
    assert result['diagnostics'][0]['location']['file'] == str(source)
    assert result['diagnostics'][0]['location']['line'] == 1
    assert result['diagnostics'][0]['params']['detail'] == 'include_outside_workspace'
    assert 'PRIVATE_SENTINEL_DO_NOT_ECHO' not in str(result)


def test_literal_workspace_include_is_staged_with_relative_dependency(tmp_path, monkeypatch, pinned_versions):
    include = tmp_path / 'defs.vh'
    include.write_text('`define VALUE 1\n', encoding='utf-8')
    source = tmp_path / 'unit.v'
    source.write_text('`include "defs.vh"\nmodule unit; endmodule\n', encoding='utf-8')
    monkeypatch.setattr(bdcheck, 'tool_commands', lambda: {'verilator': ['verilator']})

    def run(command, **kwargs):
        staged = list(Path(kwargs['cwd']).rglob('*.vh'))
        assert len(staged) == 1 and staged[0].read_text() == '`define VALUE 1\n'
        rewritten = (Path(kwargs['cwd']) / 'sources/0/unit.v').read_text()
        assert '`include "includes/' in rewritten
        assert Path(kwargs['cwd']).as_posix() not in rewritten
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(bdcheck.subprocess, 'run', run)
    result = bdcheck.run_checks({'demo.v': 'module demo; endmodule\n'}, [source], 'demo', workspace_root=tmp_path)
    assert result['valid']


def test_checks_use_fixed_arguments_and_stage_untrusted_source_names(tmp_path, monkeypatch, pinned_versions):
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
            assert 'synth -top demo -flatten' in command[-1] and 'check -assert' in command[-1]
            (Path(kwargs['cwd']) / 'synthesis.json').write_text('{"modules":{"demo":{"cells":{"gate":{"type":"$_AND_"},"scope":{"type":"$scopeinfo"}}}}}', encoding='utf-8')
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(bdcheck.subprocess, 'run', run)
    result = bdcheck.run_checks({'demo.v': 'module demo; endmodule\n'}, [source], 'demo')
    assert result['valid']
    assert len(calls) == 2
    assert result['tools'][0]['stage'] == 'lint'
    assert result['tools'][1]['stage'] == 'synthesis'
    assert result['tools'][1]['cell_count'] == 1
    assert result['tools'][1]['scopeinfo_objects'] == 1
    assert result['tools'][1]['cells'] == {'$_AND_': 1}
    assert result['diagnostics'][0]['severity'] == 'warning'
    assert result['diagnostics'][0]['location'] == {'file': 'demo.v', 'line': 4, 'column': 8}
    assert not Path(result['tools'][0]['directory']).exists()


@pytest.mark.parametrize('case', ['missing', 'timeout', 'error'])
def test_check_failures_are_explicit(case, monkeypatch, pinned_versions):
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


def test_tool_log_overflow_is_not_a_success(monkeypatch, pinned_versions):
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


def test_strict_lint_keeps_warnings_fatal(monkeypatch, pinned_versions):
    monkeypatch.setattr(bdcheck, 'tool_commands', lambda: {'verilator': ['verilator']})

    def run(command, **kwargs):
        assert '-Wno-fatal' not in command
        kwargs['stdout'].write(b'%Warning-WIDTH: demo.v:1:1: width mismatch\n')
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(bdcheck.subprocess, 'run', run)
    result = bdcheck.run_checks({'demo.v': 'module demo; endmodule\n'}, [], 'demo', strict_lint=True)
    assert not result['valid']
    assert any(item['severity'] == 'warning' for item in result['diagnostics'])
    assert result['tools'][0]['status'] == 'failed'


def test_windows_mixed_tool_paths_restore_the_original_source():
    result = bdcheck.parse_diagnostics('verilator', '%Warning-WIDTH: sources/0\\unit.sv:7:3: width\n', {'sources/0/unit.sv': 'rtl/unit.sv'})
    assert result[0]['location'] == {'file': 'rtl/unit.sv', 'line': 7, 'column': 3}


def test_real_tools_accept_a_workspace_include(tmp_path):
    (tmp_path / 'defs.vh').write_text('`define VALUE 1\n', encoding='utf-8')
    source = tmp_path / 'unit.v'
    source.write_text('`include "defs.vh"\nmodule unit(output value); assign value = `VALUE; endmodule\n', encoding='utf-8')
    result = bdcheck.run_checks({'demo.v': 'module demo(output value); unit dut(.value(value)); endmodule\n'},
                               [source], 'demo', workspace_root=tmp_path)
    assert result['valid'], result['diagnostics']
    assert result['tools'][1]['stage'] == 'synthesis'


def test_real_lint_pass_does_not_mean_synthesizable():
    source = 'module demo(input clk, rst, output reg value); always @(posedge clk or posedge rst) value <= ~value; endmodule\n'
    result = bdcheck.run_checks({'demo.v': source}, [], 'demo')
    assert result['tools'][0]['status'] == 'passed'
    assert result['tools'][1]['status'] == 'failed'
    assert not result['valid']
    error = next(item for item in result['diagnostics'] if item['severity'] == 'error' and item['params']['tool'] == 'yosys')
    assert error['location']['file'] == 'demo.v'
    assert error['params']['stage'] == 'synthesis'


def test_generated_warning_policy_exempts_only_the_known_design_slice():
    from scripts.check_hdl import unexpected_generated_warnings

    warning = {'severity': 'warning', 'location': {'file': 'connections_bd.v'},
               'params': {'tool': 'verilator', 'rule': 'UNUSEDSIGNAL', 'detail': "Bits of signal are not used: 'data'[11:8]"}}
    files = {'connections_bd.v': ''}
    assert not unexpected_generated_warnings('examples/semantic/connections.json', files, [warning])
    assert unexpected_generated_warnings('another-design', files, [warning]) == [warning]
    changed = {**warning, 'params': {**warning['params'], 'rule': 'WIDTHTRUNC'}}
    assert unexpected_generated_warnings('examples/semantic/connections.json', files, [changed]) == [changed]