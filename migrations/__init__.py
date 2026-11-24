from copy import deepcopy

from core.design import DesignFormatError, migrate
from core.diagnostics import issue


CURRENT_DESIGN_VERSION = 4
CURRENT_LAYOUT_VERSION = 1


def split_project(raw):
    if not isinstance(raw, dict) or "layout" not in raw:
        return raw, None, False
    if "design" in raw:
        version = raw.get("schema_version", 1)
        if set(raw) - {"schema_version", "design", "layout"} or type(version) is not int or version != 1:
            raise DesignFormatError(issue("D001", {"path": "$"}, reason="migration_envelope"))
        document = deepcopy(raw["design"])
    else:
        document = deepcopy(raw)
        document.pop("layout")
    if isinstance(document, dict) and type(document.get("schema_version")) is int and document["schema_version"] == 1 and "modules" in document:
        document.pop("schema_version")
    return document, deepcopy(raw["layout"]), True


def upgrade_layout(layout):
    from bdgui import check_layout

    result = check_layout(deepcopy(layout))
    result["schema_version"] = CURRENT_LAYOUT_VERSION
    result.setdefault("scopes", {})
    return result


def merge_layout(embedded, sidecar):
    layout = upgrade_layout(embedded)
    if sidecar is not None and upgrade_layout(sidecar) != layout:
        raise DesignFormatError(issue("D001", {"path": "$.layout"}, reason="migration_layout_conflict"))
    return layout


def upgrade_design(document, library):
    if isinstance(document, dict) and document.get("schema_version") == 5:
        return migrate(document, library)
    return migrate(document, library, target_version=CURRENT_DESIGN_VERSION)