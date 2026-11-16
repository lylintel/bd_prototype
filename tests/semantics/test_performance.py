from copy import deepcopy
import gc
import os
from pathlib import Path

import pytest

from core.semantic import ValidationChanges, validate
from scripts.synthetic_design import benchmark, run_isolated, synthetic_design


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


def test_2000_instance_measurement_runs_in_a_fresh_process():
    result = run_isolated(instance_count=2000, connections_per_instance=4, seed=20261112, samples=11)
    assert result["instances"] == 2000 and result["nets"] == 8000
    assert len(result["samples_ms"]) >= 11
    assert result["pid"] != os.getpid()
    assert result["budget_passed"] == (result["median_ms"] < 300 and result["max_ms"] < 600)
    assert result["python"] and result["platform"] and result["processor"]
    assert result["hooks"]["trace"] is None and result["hooks"]["profile"] is None


@pytest.mark.parametrize("mode", ["on", "off"])
def test_samples_collect_gc_and_restore_caller_state(monkeypatch, mode):
    from scripts import synthetic_design as measuring

    original = gc.isenabled()
    collections, states = [], []
    monkeypatch.setattr(gc, "collect", lambda: collections.append(True))
    monkeypatch.setattr(measuring, "validate", lambda *args: states.append(gc.isenabled()) or [])
    result = benchmark(instance_count=10, samples=11, gc_mode=mode)
    assert len(collections) == len(states) == len(result["samples_ms"]) == 11
    assert states == [mode == "on"] * 11
    assert gc.isenabled() == original
    assert result["gc_mode"] == mode and result["collect_before_sample"] is True
    assert len(result["design_sha256"]) == 64


def test_measurement_restores_gc_after_validation_failure(monkeypatch):
    from scripts import synthetic_design as measuring

    original = gc.isenabled()

    def fail(*args):
        raise RuntimeError("validation failed")

    monkeypatch.setattr(measuring, "validate", fail)
    with pytest.raises(RuntimeError):
        benchmark(instance_count=10, gc_mode="off" if original else "on")
    assert gc.isenabled() == original


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


@pytest.mark.parametrize("strict,expected", [(False, 0), (True, 1)])
def test_local_budget_policy_is_warning_unless_strict(capsys, strict, expected):
    from scripts.check import performance_status

    result = {"median_ms": 400.0, "max_ms": 700.0, "budget_passed": False}
    assert performance_status(result, strict=strict) == expected
    output = capsys.readouterr().out
    assert "WARNING" in output and "400.000" in output and "700.000" in output
    assert performance_status({"median_ms": 100.0, "max_ms": 200.0, "budget_passed": True}, strict=strict) == 0


@pytest.mark.parametrize("exceeded", [False, True])
def test_five_ci_runs_preserve_data_and_choose_nonblocking(monkeypatch, tmp_path, exceeded):
    from scripts import perf_gate

    base = {"schema_version": 1, "median_ms": 100.0, "max_ms": 200.0, "budget_passed": True,
            "processor": "test CPU", "cpu_count": 4, "python": "3.14", "platform": "Linux", "design_sha256": "a" * 64}
    runs = [dict(base) for _ in range(5)]
    if exceeded:
        runs[2].update(median_ms=350.0, max_ms=700.0, budget_passed=False)
    pending = iter(runs)
    monkeypatch.setattr(perf_gate, "run_isolated", lambda: next(pending))
    report = perf_gate.collect_runs(5)
    assert report["non_blocking"] is exceeded
    assert report["runs"] == runs
    summary = tmp_path / "summary.md"
    perf_gate.write_summary(report, summary)
    text = summary.read_text(encoding="utf-8")
    assert all(f"| {index} |" in text for index in range(1, 6))
    assert "300" in text and "600" in text and "test CPU" in text
    assert perf_gate.enforce(report) == (1 if exceeded else 0)


def test_subprocess_protocol_failure_is_not_a_budget_warning(monkeypatch):
    from types import SimpleNamespace
    from scripts import synthetic_design as measuring

    monkeypatch.setattr(measuring.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="{}", stderr="broken child", returncode=1))
    with pytest.raises(RuntimeError, match="broken child"):
        run_isolated()