import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from ip_import.parser import parse_file


FIXTURES = Path(__file__).parent / "fixtures" / "verilog"


def projection(result):
    return {
        "modules": [[module.id, [[parameter.name, parameter.default] for parameter in module.parameters],
                     [[port.name, port.dir, list(port.range) if port.range is not None else None, bool(port.signed)]
                      for port in module.ports]] for module in result.modules],
        "diagnostics": [[item.code, item.line] for item in result.diagnostics if item.severity == "error"],
    }


def test_all_fixtures_match_interface_golden():
    paths = sorted([*FIXTURES.glob("*.v"), *FIXTURES.glob("*.sv")])
    assert len(paths) >= 12
    actual = {}
    for path in paths:
        result = parse_file(path, workspace_root=FIXTURES)
        actual[path.name] = projection(result)
        for module in result.modules:
            assert module.source.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
            assert module.source.path == path.name
            assert all(isinstance(port.width, str) for port in module.ports)
    encoded = (json.dumps(actual, indent=2) + "\n").encode("utf-8")
    assert encoded == (FIXTURES / "interfaces.golden.json").read_bytes()


def test_localparam_width_is_not_frozen_at_default():
    result = parse_file(FIXTURES / "local.v")
    assert result.modules[0].parameters[0].name == "WIDTH"
    assert len(result.modules[0].parameters) == 1
    assert "WIDTH * 2" in result.modules[0].ports[0].width
    assert "TOTAL" not in result.modules[0].ports[0].width


@pytest.mark.parametrize("text,code", [
    ('`include "secret.v"\nmodule danger; endmodule\n', "IP_PARSE_PREPROCESSOR"),
    ("module weird(input [1:0][3:0] value); endmodule\n", "IP_PARSE_UNSUPPORTED"),
])
def test_unsupported_inputs_return_diagnostics(tmp_path, text, code):
    path = tmp_path / "input.sv"
    path.write_bytes(text.encode())
    result = parse_file(path)
    assert not result.modules
    assert result.diagnostics[0].code == code
    assert result.diagnostics[0].line >= 1


def test_missing_outside_and_large_sources_are_diagnostics(tmp_path):
    assert parse_file(tmp_path / "missing.v").diagnostics
    assert parse_file(FIXTURES / "ansi.v", workspace_root=tmp_path).diagnostics[0].code == "IP_PARSE_PATH"
    path = tmp_path / "large.v"
    path.write_bytes(b" " * (1024 * 1024 + 1))
    assert parse_file(path).diagnostics[0].code == "IP_PARSE_SIZE"


@pytest.mark.parametrize("failure,code", [
    (subprocess.TimeoutExpired("yosys", 1), "IP_PARSE_TIMEOUT"),
    (FileNotFoundError("yosys"), "IP_PARSE_TOOL"),
])
def test_tool_failure_and_timeout_are_diagnostics(monkeypatch, failure, code):
    def timeout(*args, **kwargs):
        raise failure

    monkeypatch.setattr("ip_import.parser.subprocess.run", timeout)
    assert parse_file(FIXTURES / "ansi.v").diagnostics[0].code == code


def test_parser_warning_does_not_discard_valid_modules(monkeypatch):
    run = subprocess.run

    def warning(*args, **kwargs):
        result = run(*args, **kwargs)
        kwargs["stdout"].write(b"\nWarning: example warning\n")
        return result

    monkeypatch.setattr("ip_import.parser.subprocess.run", warning)
    result = parse_file(FIXTURES / "ansi.v")
    assert result.modules[0].id == "ansi"
    assert result.diagnostics[0].severity == "warning"
    assert result.diagnostics[0].code == "IP_PARSE_WARNING"


def test_syntax_error_has_source_location():
    result = parse_file(FIXTURES / "syntax_error.v")
    assert not result.modules
    diagnostic = result.diagnostics[0]
    assert diagnostic.line == 2
    assert diagnostic.path == "syntax_error.v"
    assert diagnostic.message