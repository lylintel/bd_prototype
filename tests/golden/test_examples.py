import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

import bdtool


ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).resolve().parent
EXAMPLES = tuple(sorted((ROOT / "examples").glob("*.json")))


def port_snapshot(port):
    return {"direction": port.direction, "range": list(port.bounds) if port.bounds is not None else None,
            "signed": port.signed, "width": port.width}


def endpoint_snapshot(endpoint):
    return f"{endpoint.instance}.{endpoint.port}" if endpoint.instance else f"@{endpoint.port}"


def capture(example):
    design = bdtool.load_design(example)
    validation = {
        "valid": True,
        "diagnostics": [],
        "summary": f"Valid: {design.name} ({len(design.instances)} instances, {len(design.nets)} nets)",
        "name": design.name,
        "wrapper_name": design.wrapper_name,
        "ports": {name: port_snapshot(port) for name, port in design.ports.items()},
        "instances": {name: {"module": instance.module, "parameters": instance.parameters,
            "ports": {port_name: port_snapshot(port) for port_name, port in instance.ports.items()}}
            for name, instance in design.instances.items()},
        "nets": [{"name": net.name, "shape": port_snapshot(net.shape),
                  "driver": endpoint_snapshot(net.driver),
                  "sinks": [endpoint_snapshot(sink) for sink in net.sinks]} for net in design.nets],
        "sources": [Path(os.path.relpath(source, ROOT)).as_posix() for source in design.sources],
    }
    outputs = {name: text.encode("utf-8") for name, text in bdtool.render_verilog(design).items()}
    outputs["validation.json"] = (json.dumps(validation, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return outputs


def assert_matches_golden(example, actual):
    directory = GOLDEN / example.stem
    expected_names = {path.name for path in directory.iterdir()} if directory.exists() else set()
    assert set(actual) == expected_names, f"Missing or extra golden files: {example.name}"
    for name, content in actual.items():
        assert content == (directory / name).read_bytes(), f"Golden mismatch: {example.stem}/{name}"


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda example: example.stem)
def test_example_matches_golden(example):
    assert_matches_golden(example, capture(example))


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda example: example.stem)
def test_cli_outputs_match_golden(example, tmp_path):
    checked = subprocess.run([sys.executable, "-m", "bdtool", "validate", str(example)],
                             cwd=ROOT, capture_output=True, text=True, timeout=30)
    expected = json.loads((GOLDEN / example.stem / "validation.json").read_text(encoding="utf-8"))
    assert checked.returncode == 0, checked.stderr
    assert checked.stdout.strip() == expected["summary"]
    generated = subprocess.run([sys.executable, "-m", "bdtool", "generate", str(example), "-o", str(tmp_path)],
                               cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert generated.returncode == 0, generated.stderr
    expected_files = list((GOLDEN / example.stem).glob("*.v"))
    assert {path.name for path in tmp_path.iterdir()} == {path.name for path in expected_files}
    for path in expected_files:
        assert (tmp_path / path.name).read_bytes() == path.read_bytes()


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda example: example.stem)
def test_single_character_generator_regression_is_detected(example):
    original = bdtool.render_verilog

    def changed(design):
        result = original(design)
        name = f"{design.name}.v"
        result[name] = result[name].replace("module", "Module", 1)
        return result

    with patch.object(bdtool, "render_verilog", side_effect=changed):
        with pytest.raises(AssertionError, match="Golden mismatch"):
            assert_matches_golden(example, capture(example))


def test_golden_covers_every_example():
    assert EXAMPLES, "No examples found"
    directories = {path.name for path in GOLDEN.iterdir() if path.is_dir() and not path.name.startswith((".", "__"))}
    assert directories == {example.stem for example in EXAMPLES}


if __name__ == "__main__":
    if sys.argv[1:] != ["--update"]:
        raise SystemExit("Use python -m pytest tests/golden; baseline regeneration requires --update.")
    for example in EXAMPLES:
        destination = GOLDEN / example.stem
        destination.mkdir(parents=True, exist_ok=True)
        for name, contents in capture(example).items():
            (destination / name).write_bytes(contents)
        print(f"Updated {example.stem}")