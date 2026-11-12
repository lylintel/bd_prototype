import json
from pathlib import Path

import pytest

from bdip import migrate_legacy_modules
from core.design import migrate


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def bundle():
    original = json.loads((ROOT / "examples/counter_compare.json").read_text(encoding="utf-8"))
    library = tuple(migrate_legacy_modules(original, ROOT / "examples", workspace_root=ROOT).values())
    return migrate(original, library), library