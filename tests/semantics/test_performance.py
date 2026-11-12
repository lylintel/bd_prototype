from copy import deepcopy
from pathlib import Path

import pytest

from core.semantic import ValidationChanges, validate
from scripts.synthetic_design import benchmark, synthetic_design


def test_synthetic_generator_is_configurable_and_deterministic():
    first, library = synthetic_design(instance_count=40, connections_per_instance=3, seed=17)
    second, other_library = synthetic_design(instance_count=40, connections_per_instance=3, seed=17)
    different, _ = synthetic_design(instance_count=40, connections_per_instance=3, seed=18)
    assert first == second and library == other_library
    assert first != different
    assert len(first["instances"]) == 40 and len(first["nets"]) == 120
    assert len(library[0].ports) == 6
    assert validate(first, library) == []


@pytest.mark.parametrize("options", [{"instance_count": 0}, {"instance_count": True},
                                    {"connections_per_instance": 0}, {"connections_per_instance": 1.5},
                                    {"instance_count": 20000, "connections_per_instance": 8}])
def test_synthetic_generator_rejects_invalid_sizes(options):
    with pytest.raises(ValueError):
        synthetic_design(**options)


def test_full_validation_is_pure_and_does_not_read_sources(monkeypatch):
    document, library = synthetic_design(instance_count=50, connections_per_instance=4)
    original = deepcopy((document, library))

    def forbidden(*args, **kwargs):
        raise AssertionError("validation must not read files")

    with monkeypatch.context() as patch:
        patch.setattr("builtins.open", forbidden)
        patch.setattr(Path, "read_text", forbidden)
        patch.setattr(Path, "read_bytes", forbidden)
        assert validate(document, library) == validate(document, library) == []
        broken = deepcopy(document)
        broken["nets"][0]["endpoints"][1]["port"] = "missing"
        assert any(item.code == "E004" for item in validate(broken, library))
    assert (document, library) == original


def test_2000_instance_full_validation_stays_below_300ms():
    result = benchmark(instance_count=2000, connections_per_instance=4, seed=20261112, samples=11)
    assert result["instances"] == 2000 and result["nets"] == 8000
    assert len(result["samples_ms"]) >= 10
    assert result["median_ms"] < 300 and result["max_ms"] < 600, result


def test_parameter_combinations_are_resolved_once(monkeypatch):
    from core import resolve as resolver

    document, library = synthetic_design(instance_count=2000)
    document["instances"][1]["params"]["WIDTH"] = 16
    calls = {"parameters": 0, "ports": 0}
    original_parameters, original_ports = resolver.parameters, resolver.instance_ports

    def parameters(*args):
        calls["parameters"] += 1
        return original_parameters(*args)

    def ports(*args):
        calls["ports"] += 1
        return original_ports(*args)

    monkeypatch.setattr(resolver, "parameters", parameters)
    monkeypatch.setattr(resolver, "instance_ports", ports)
    result = resolver.resolve(document, library)
    assert calls == {"parameters": 2, "ports": 2}
    assert result.instances["unit_0"].ports is result.instances["unit_2"].ports
    assert result.instances["unit_1"].ports["input_0"].width == 16


def test_change_hints_share_one_full_resolve_and_preserve_findings(monkeypatch):
    from core import semantic

    document, library = synthetic_design(instance_count=30)
    document["nets"][0]["endpoints"][1]["port"] = "missing"
    expected = validate(document, library)
    original_resolve = semantic.resolve
    calls = []

    def resolve(*args):
        calls.append(args)
        return original_resolve(*args)

    monkeypatch.setattr(semantic, "resolve", resolve)
    changes = ValidationChanges(instances=frozenset({"unit_0"}), nets=frozenset({document["nets"][0]["name"]}))
    assert validate(document, library, changes=changes) == expected
    assert len(calls) == 1