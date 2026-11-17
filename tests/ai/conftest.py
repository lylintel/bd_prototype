import json
from pathlib import Path

import pytest

from bdip import migrate_legacy_modules
from core.design import migrate


@pytest.fixture
def bundle():
    root = Path(__file__).resolve().parents[2]
    raw = json.loads((root / "examples/counter_compare.json").read_text(encoding="utf-8"))
    library = tuple(migrate_legacy_modules(raw, root / "examples", workspace_root=root).values())
    return migrate(raw, library), library