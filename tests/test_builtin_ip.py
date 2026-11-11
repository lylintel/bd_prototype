import json
from pathlib import Path
import shutil
import subprocess

import pytest

import bdtool
from ip_import.library import IpLibrary, Upload


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "ip_library" / "builtin"
MANIFEST = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))
CASES = [(entry, index, values) for entry in MANIFEST["entries"] for index, values in enumerate(entry["tests"])]


@pytest.mark.parametrize("entry,index,values", CASES, ids=[f"{entry['id']}-{index}" for entry, index, _ in CASES])
def test_builtin_rtl_behavior(entry, index, values, tmp_path):
    compiler, simulator = shutil.which("iverilog"), shutil.which("vvp")
    assert compiler and simulator, "Icarus Verilog and vvp are required"
    directory = BUNDLE / entry["id"] / entry["version"]
    source = directory / "src" / f"{entry['id']}.v"
    bench = directory / "tb.sv"
    assert source.is_file() and bench.is_file()
    executable = tmp_path / "simulation"
    compiled = subprocess.run([compiler, "-g2012", "-s", "tb", *[f"-Ptb.{name}={value}" for name, value in values.items()],
                               "-o", str(executable), str(source), str(bench)], capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stderr
    assert "warning:" not in compiled.stderr.lower(), compiled.stderr
    result = subprocess.run([simulator, str(executable)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"PASS {entry['id']}" in result.stdout


def test_builtin_manifest_is_complete_and_original():
    assert MANIFEST["schema_version"] == 1
    assert MANIFEST["origin"] == "original"
    assert MANIFEST["license"] == "MIT"
    names = [entry["id"] for entry in MANIFEST["entries"]]
    assert len(names) == len(set(names)) >= 17
    for entry in MANIFEST["entries"]:
        assert entry["description"] and entry["tags"] and entry["tests"]
        directory = BUNDLE / entry["id"] / entry["version"]
        assert (directory / "src" / f"{entry['id']}.v").is_file()
        assert (directory / "tb.sv").is_file()
    assert "MIT License" in (BUNDLE / "LICENSE").read_text(encoding="utf-8")


def test_builtin_catalog_and_hdl_match_import_pipeline():
    from ip_import.builtin import capture_bundle

    outputs = capture_bundle(ROOT)
    for relative, content in outputs.items():
        assert content == (ROOT / relative).read_bytes(), relative


def test_readonly_builtin_catalog_does_not_create_private_index(tmp_path):
    shutil.copytree(BUNDLE, tmp_path / "ip_library" / "builtin")
    library = IpLibrary(tmp_path)
    entries = library.entries()
    assert len(entries) == len(MANIFEST["entries"])
    assert all(entry["origin"] == "builtin" and entry["usable"] for entry in entries)
    assert all(entry["metadata"]["source"]["license"] == "MIT" for entry in entries)
    assert not (tmp_path / "ip_library/index.json").exists()
    original = (tmp_path / "ip_library/builtin/index.json").read_bytes()
    list(library.import_sources([Upload("user_unit.v", b"module user_unit(output value); assign value=1'b1; endmodule\n")]))
    private = json.loads((tmp_path / "ip_library/index.json").read_text(encoding="utf-8"))
    assert set(private["entries"]) == {"user_unit@1.0.0"}
    assert (tmp_path / "ip_library/builtin/index.json").read_bytes() == original
    assert len(library.entries()) == len(MANIFEST["entries"]) + 1


def test_every_builtin_generated_wrapper_compiles(tmp_path):
    corpus = json.loads((ROOT / "tests/fixtures/builtin-hdl.golden.json").read_text(encoding="utf-8"))
    assert set(corpus) == {entry["id"] for entry in MANIFEST["entries"]}
    for name, example in corpus.items():
        generated = []
        for filename, text in example["files"].items():
            destination = tmp_path / filename
            destination.write_bytes(text.encode("utf-8"))
            generated.append(str(destination))
        compiled = subprocess.run([shutil.which("iverilog"), "-g2012", "-s", example["wrapper"], "-o", str(tmp_path / name),
                                   *generated, *(str(ROOT / source) for source in example["sources"])],
                                  capture_output=True, text=True, timeout=30)
        assert compiled.returncode == 0 and "warning:" not in compiled.stderr.lower(), compiled.stderr


def test_generated_builtin_counter_example_simulates(tmp_path):
    design = bdtool.load_design(ROOT / "examples/builtin_counter.json")
    generated = []
    for name, text in bdtool.render_verilog(design).items():
        path = tmp_path / name
        path.write_bytes(text.encode("utf-8"))
        generated.append(str(path))
    executable = tmp_path / "simulation"
    compiled = subprocess.run([shutil.which("iverilog"), "-g2012", "-s", "tb", "-o", str(executable),
                               *generated, *(str(path) for path in design.sources), str(BUNDLE / "examples/counter_tb.sv")],
                              capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0 and "warning:" not in compiled.stderr.lower(), compiled.stderr
    result = subprocess.run([shutil.which("vvp"), str(executable)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0 and "PASS builtin_counter_bd" in result.stdout, result.stdout + result.stderr


@pytest.mark.parametrize("field", ["source_sha256", "interface_hash"])
def test_builtin_regeneration_requires_version_bump(tmp_path, monkeypatch, field):
    import ip_import.builtin as builtin

    index_path = tmp_path / "ip_library/builtin/index.json"
    index_path.parent.mkdir(parents=True)
    original = (BUNDLE / "index.json").read_bytes()
    index_path.write_bytes(original)
    changed = json.loads(original)
    entry = next(iter(changed["entries"].values()))
    entry[field] = "f" * 64
    monkeypatch.setattr(builtin, "ROOT", tmp_path)
    monkeypatch.setattr(builtin, "capture_bundle", lambda: {"ip_library/builtin/index.json": json.dumps(changed).encode()})
    with pytest.raises(ValueError):
        builtin.main(["--update"])
    assert index_path.read_bytes() == original