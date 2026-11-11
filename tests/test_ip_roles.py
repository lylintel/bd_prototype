from dataclasses import replace
import json
from pathlib import Path

import pytest

from bdip import IpPort, IpRole, migrate_legacy_modules
from ip_import.roles import suggest_role, suggest_roles


ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "fixtures" / "roles.golden.json"
CASES = json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name,expected", CASES.items())
def test_name_suggestions(name, expected):
    role = suggest_role(IpPort(name, "in", "1"))
    assert (role.to_dict() if role is not None else None) == expected


def test_roles_match_byte_golden():
    actual = {}
    for name in CASES:
        role = suggest_role(IpPort(name, "in", "1"))
        actual[name] = role.to_dict() if role is not None else None
    assert (json.dumps(actual, indent=2) + "\n").encode() == GOLDEN.read_bytes()


@pytest.mark.parametrize("name", ["clk", "rst_n", "rst", "data"])
def test_confirmed_role_is_never_replaced(name):
    role = IpRole("data", 1.0, True)
    assert suggest_role(IpPort(name, "in", "1", role=role)) is role


def test_bulk_suggestions_preserve_original_and_confirmations():
    example = ROOT / "examples" / "counter_compare.json"
    metadata = migrate_legacy_modules(json.loads(example.read_text(encoding="utf-8")), example.parent, workspace_root=ROOT)["counter"]
    original = metadata.to_dict()
    updated = suggest_roles(metadata)
    assert metadata.to_dict() == original
    assert updated.ports[0].role.kind == "clock"
    assert updated.ports[1].role.asynchronous == "unknown"
    confirmed = replace(updated.ports[0], role=IpRole("data", 1.0, True))
    preserved = suggest_roles(replace(updated, ports=(confirmed, *updated.ports[1:])))
    assert preserved.ports[0].role is confirmed.role
    assert preserved.source == metadata.source


def test_unmatched_unconfirmed_role_is_preserved():
    role = IpRole("control", 0.6, False)
    assert suggest_role(IpPort("enable", "in", "1", role=role)) is role