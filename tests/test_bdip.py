import copy
from dataclasses import is_dataclass, replace
import hashlib
import json
from pathlib import Path

import pytest

import bdip
import bdtool


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def counter_ip():
    return {
        "schema_version": 1,
        "id": "counter",
        "version": "1.0.0",
        "display_name": "counter",
        "description": "Parameterized counter",
        "tags": ["counter"],
        "source": {"kind": "verilog", "path": "rtl/counter.v", "sha256": "a" * 64, "license": "NOASSERTION"},
        "language": "verilog-2005",
        "parameters": [{"name": "WIDTH", "type": "int", "default": "8", "min": 1}],
        "ports": [
            {"name": "clk", "dir": "in", "width": "1", "role": {"kind": "clock", "confidence": 0.95, "confirmed": False}},
            {"name": "rst", "dir": "in", "width": "1", "role": {"kind": "reset", "polarity": "high", "async": False, "confidence": 0.9, "confirmed": False}},
            {"name": "count", "dir": "out", "width": "WIDTH"},
        ],
        "interfaces": [],
    }


@pytest.mark.parametrize("change", [
    {},
    {"parameters": []},
    {"ports": [{"name": "pad", "dir": "inout", "width": "1"}]},
    {"ports": [{"name": "data", "dir": "out", "width": "$clog2(DEPTH)", "signed": True, "range": [0, "WIDTH - 1"]}]},
    {"parameters": [{"name": "DEPTH", "type": "int", "default": "2 ** 8", "min": 1, "max": 1024}]},
    {"language": "systemverilog", "ports": []},
    {"ports": [{"name": "reset_n", "dir": "in", "width": "1", "role": {"kind": "reset", "polarity": "low", "async": "unknown", "confidence": 0.4, "confirmed": False}}]},
], ids=["counter", "no-parameters", "inout", "symbolic-width-signed-ascending", "expression-default", "systemverilog", "unknown-reset-timing"])
def test_valid_schema_and_dataclass_roundtrip(counter_ip, change):
    document = {**counter_ip, **change}
    bdip.IP_VALIDATOR.validate(document)
    metadata = bdip.IpMetadata.from_dict(document)
    assert is_dataclass(metadata)
    assert is_dataclass(metadata.source)
    assert all(is_dataclass(port) for port in metadata.ports)
    assert all(is_dataclass(parameter) for parameter in metadata.parameters)
    assert metadata.to_dict() == document


@pytest.mark.parametrize("field,value", [
    ("schema_version", 0), ("schema_version", 2), ("schema_version", True),
    ("id", "../counter"), ("id", "module"), ("id", "9counter"), ("id", "counter\n"),
    ("version", "1.0"), ("version", "1.0.0\n"), ("language", "python"), ("tags", ["counter", "counter"]),
    ("parameters", [{"name": "WIDTH", "type": "int", "default": 8}]),
    ("ports", [{"name": "data", "dir": "input", "width": "1"}]),
    ("ports", [{"name": "data", "dir": "out", "width": 8}]),
    ("ports", [{"name": "data", "dir": "out", "width": " "}]),
    ("ports", [{"name": "input", "dir": "in", "width": "1"}]),
    ("ports", [{"name": "clk", "dir": "in", "width": "1", "role": {"kind": "clock", "confidence": 1.1, "confirmed": False}}]),
    ("ports", [{"name": "clk", "dir": "in", "width": "1", "role": {"kind": "clock", "confidence": 0.9}}]),
    ("ports", [{"name": "data", "dir": "out", "width": "1", "range": [0]}]),
    ("source", {"kind": "verilog", "path": "a.v", "sha256": "not-a-hash", "license": "MIT"}),
    ("source", {"kind": "verilog", "path": "a.v", "sha256": "a" * 64 + "\n", "license": "MIT"}),
    ("source", {"kind": "verilog", "path": "a.v\u0000", "sha256": "a" * 64, "license": "MIT"}),
    ("source", {"kind": "verilog", "path": "a.v", "sha256": "a" * 64}),
    ("source", {"kind": "verilog", "path": "C:\\outside.v", "sha256": "a" * 64, "license": "MIT"}),
    ("unexpected", True),
])
def test_invalid_schema_has_structured_error(counter_ip, field, value):
    counter_ip[field] = value
    assert not bdip.IP_VALIDATOR.is_valid(counter_ip)
    with pytest.raises(bdip.IpMetadataError) as error:
        bdip.IpMetadata.from_dict(counter_ip)
    assert error.value.code in {"IP_SCHEMA_INVALID", "IP_SCHEMA_VERSION"}
    assert error.value.location
    assert str(error.value)


@pytest.mark.parametrize("case", ["port", "parameter", "cross-kind", "limits"])
def test_semantic_conflicts_rejected(counter_ip, case):
    if case == "port":
        counter_ip["ports"].append({"name": "clk", "dir": "out", "width": "8"})
    elif case == "parameter":
        counter_ip["parameters"].append({"name": "WIDTH", "type": "int", "default": "16"})
    elif case == "cross-kind":
        counter_ip["ports"].append({"name": "WIDTH", "dir": "out", "width": "1"})
    else:
        counter_ip["parameters"][0].update(min=16, max=1)
    with pytest.raises(bdip.IpMetadataError):
        bdip.IpMetadata.from_dict(counter_ip)


def test_version_required_and_document_is_independent(counter_ip):
    metadata = bdip.IpMetadata.from_dict(counter_ip)
    counter_ip["ports"][0]["name"] = "changed"
    result = metadata.to_dict()
    result["tags"].append("changed")
    assert metadata.ports[0].name == "clk"
    assert metadata.to_dict()["tags"] == ["counter"]
    del result["schema_version"]
    with pytest.raises(bdip.IpMetadataError) as error:
        bdip.IpMetadata.from_dict(result)
    assert error.value.code == "IP_SCHEMA_VERSION"


def test_load_save_is_deterministic_and_validation_precedes_write(counter_ip, tmp_path):
    metadata = bdip.IpMetadata.from_dict(counter_ip)
    path = tmp_path / "ip.json"
    bdip.save_ip(metadata, path)
    original = path.read_bytes()
    loaded = bdip.load_ip(path)
    assert loaded.to_dict() == counter_ip
    bdip.save_ip(loaded, path)
    assert path.read_bytes() == original
    assert original.endswith(b"\n") and b"\r" not in original
    invalid = replace(metadata, version="bad")
    with pytest.raises(bdip.IpMetadataError):
        bdip.save_ip(invalid, path)
    assert path.read_bytes() == original


@pytest.mark.parametrize("contents", [b'{"schema_version":1,"schema_version":1}', b'{', b'\xff', b'[]'])
def test_malformed_json_is_a_domain_error(tmp_path, contents):
    path = tmp_path / "bad.json"
    path.write_bytes(contents)
    with pytest.raises(bdip.IpMetadataError):
        bdip.load_ip(path)


def test_load_is_bounded_and_missing_file_is_a_domain_error(tmp_path):
    with pytest.raises(bdip.IpMetadataError):
        bdip.load_ip(tmp_path / "missing.json")
    path = tmp_path / "large.json"
    path.write_bytes(b" " * (bdip.MAX_METADATA_BYTES + 1))
    with pytest.raises(bdip.IpMetadataError) as error:
        bdip.load_ip(path)
    assert error.value.code == "IP_METADATA_TOO_LARGE"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_objects_are_rejected_before_use(counter_ip, value):
    counter_ip["ports"][0]["role"]["confidence"] = value
    with pytest.raises(bdip.IpMetadataError):
        bdip.IpMetadata.from_dict(counter_ip)


def test_direct_objects_obey_size_limit(counter_ip):
    counter_ip["description"] = "x" * bdip.MAX_METADATA_BYTES
    with pytest.raises(bdip.IpMetadataError) as error:
        bdip.IpMetadata.from_dict(counter_ip)
    assert error.value.code == "IP_METADATA_TOO_LARGE"


def test_failed_atomic_replace_preserves_destination(counter_ip, tmp_path, monkeypatch):
    path = tmp_path / "ip.json"
    path.write_bytes(b"original")

    def fail_replace(*args, **kwargs):
        raise OSError("simulated write failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(bdip.IpMetadataError) as error:
        bdip.save_ip(bdip.IpMetadata.from_dict(counter_ip), path)
    assert error.value.code == "IP_FILE_WRITE"
    assert path.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [path]


def test_identifiers_reject_existing_core_keywords(counter_ip):
    for keyword in bdtool.KEYWORDS:
        counter_ip["id"] = keyword
        assert not bdip.IP_VALIDATOR.is_valid(counter_ip), keyword


@pytest.mark.parametrize("example", sorted((ROOT / "examples").glob("*.json")), ids=lambda path: path.stem)
def test_legacy_migration_preserves_behavior_and_source_evidence(example, tmp_path):
    original_bytes = example.read_bytes()
    document = json.loads(original_bytes)
    snapshot = copy.deepcopy(document)
    before = bdtool.render_verilog(bdtool.load_design(example))
    migrated = bdip.migrate_legacy_modules(document, example.parent, workspace_root=ROOT)
    assert list(migrated) == list(document["modules"])
    for name, metadata in migrated.items():
        legacy = document["modules"][name]
        assert metadata.id == name and metadata.schema_version == 1
        assert metadata.source.license == "NOASSERTION"
        source = (example.parent / legacy["sources"][0]).resolve()
        assert metadata.source.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
        assert {parameter.name: parameter.default for parameter in metadata.parameters} == {
            key: str(value["default"]) for key, value in legacy.get("parameters", {}).items()}
        assert all(port.role is None for port in metadata.ports)
        for port in metadata.ports:
            assert port.to_dict().get("range") == legacy["ports"][port.name].get("range")
        target = tmp_path / name / "ip.json"
        bdip.save_ip(metadata, target)
        loaded = bdip.load_ip(target)
        assert (target.parent / loaded.source.path).resolve() == source
        assert loaded.source.sha256 == metadata.source.sha256
    assert document == snapshot
    assert example.read_bytes() == original_bytes
    assert bdtool.render_verilog(bdtool.load_design(example)) == before


def test_migration_retains_multiple_sources_bounds_signedness_and_constraints(tmp_path):
    for name in ("first.v", "second.v"):
        (tmp_path / name).write_text("module stub; endmodule\n", encoding="utf-8")
    document = {"modules": {"unit": {
        "sources": ["first.v", "second.v"],
        "parameters": {"WIDTH": {"default": 8, "min": 1, "max": 32}},
        "ports": {"ascending": {"direction": "input", "range": [0, "WIDTH - 1"], "signed": True},
                  "single": {"direction": "output", "range": [0, 0]},
                  "scalar": {"direction": "input"}},
    }}}
    metadata = bdip.migrate_legacy_modules(document, tmp_path, workspace_root=tmp_path, license_name="MIT")["unit"]
    assert metadata.parameters[0].to_dict() == {"name": "WIDTH", "type": "int", "default": "8", "min": 1, "max": 32}
    assert metadata.source.license == "MIT"
    assert metadata.additional_sources[0].path == "second.v"
    assert metadata.additional_sources[0].sha256 == hashlib.sha256((tmp_path / "second.v").read_bytes()).hexdigest()
    assert metadata.ports[0].signed is True
    assert "WIDTH - 1" in metadata.ports[0].width
    assert "?" in metadata.ports[0].width
    assert metadata.ports[1].to_dict()["range"] == [0, 0]
    assert "range" not in metadata.ports[2].to_dict()
    original = (tmp_path / "first.v").read_bytes()
    with pytest.raises(bdip.IpMetadataError) as error:
        bdip.save_ip(metadata, tmp_path / "first.v")
    assert error.value.code == "IP_SOURCE_OVERWRITE"
    assert (tmp_path / "first.v").read_bytes() == original


def test_migration_rejects_sources_outside_authorized_root(tmp_path):
    inside = tmp_path / "workspace"
    inside.mkdir()
    outside = tmp_path / "outside.v"
    outside.write_text("module unit; endmodule\n", encoding="utf-8")
    document = {"modules": {"unit": {"sources": ["../outside.v"], "ports": {}}}}
    with pytest.raises(bdip.IpMetadataError) as error:
        bdip.migrate_legacy_modules(document, inside, workspace_root=inside)
    assert error.value.code == "IP_SOURCE_OUTSIDE_WORKSPACE"


def test_schema_is_a_valid_offline_draft():
    bdip.IP_VALIDATOR.check_schema(bdip.IP_VALIDATOR.schema)
    assert json.loads((ROOT / "ip.schema.json").read_text(encoding="utf-8")) == bdip.IP_VALIDATOR.schema