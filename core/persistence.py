from copy import deepcopy
import json
from pathlib import Path

import bdtool
from core.design import DesignFormatError
from core.diagnostics import issue


def canonical_document(document: dict) -> dict:
    result = deepcopy(document)
    for scope in [result, *result.get("subdesigns", {}).values()]:
        for section in ("instances", "nets"):
            if isinstance(scope.get(section), list):
                scope[section].sort(key=lambda item: item["name"])
    if "project_ips" in result:
        result["project_ips"].sort(key=lambda item: (item["id"], item["version"]))
    return result


def write_project(document: dict, layout: dict, target: Path, protected_paths: set[Path], workspace_root: Path) -> None:
    files = {
        target.name: json.dumps(canonical_document(document), sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        target.with_suffix(".layout.json").name: json.dumps(layout, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
    }
    changed = {}
    for name, content in files.items():
        path = target.parent / name
        resolved = path.resolve()
        if not resolved.is_relative_to(workspace_root.resolve()):
            raise DesignFormatError(issue("D005", {}, reason="project_output_path"))
        if resolved in protected_paths:
            raise bdtool.DesignError(f"output would overwrite an input file: {path}")
        if path.exists() and not path.is_file():
            raise bdtool.DesignError(f"output path is not a file: {path}")
        if not path.is_file() or path.read_bytes() != content.encode("utf-8"):
            changed[name] = content
    if changed:
        bdtool._write_outputs(changed, target.parent, protected_paths)