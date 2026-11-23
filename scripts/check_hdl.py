import json
from pathlib import Path

from bdcheck import run_checks
from bdip import MESSAGES
from bdgui import Workspace
from bdsemantic import prepare
from core.generation import generate_files
from ip_import.builtin import _standalone


ROOT = Path(__file__).resolve().parents[1]


def unexpected_generated_warnings(case, files, diagnostics):
    unexpected = []
    for item in diagnostics:
        if item["severity"] != "warning" or item["location"].get("file") not in files:
            continue
        params = item["params"]
        exempt = (case == "examples/semantic/connections.json" and item["location"].get("file") == "connections_bd.v"
                  and params.get("tool") == "verilator" and params.get("rule") == "UNUSEDSIGNAL"
                  and params.get("detail") == "Bits of signal are not used: 'data'[11:8]")
        if not exempt:
            unexpected.append(item)
    return unexpected


def main():
    workspace = Workspace(ROOT, "examples/counter_compare.json")
    cases = []
    examples = sorted(path for path in (ROOT / "examples").rglob("*.json") if not path.name.endswith(".layout.json"))
    catalog = ROOT / "src/ip_catalog.json"
    if catalog.exists():
        examples.append(catalog)
    for path in examples:
        loaded = workspace.load(workspace.relative(path))
        cases.append((workspace.relative(path), loaded["design"], loaded["base_dir"]))
    for entry in workspace.ip_library().entries(base_dir=ROOT):
        if entry["origin"] == "builtin":
            cases.append((entry["metadata"]["id"], _standalone(entry["metadata"]["id"], entry["definition"]), "."))
    results = []
    output = ROOT / "build/hdl-checks.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    for name, raw, base_dir in cases:
        document, library = prepare(workspace, raw, base_dir)
        language = "sv" if any(item.language == "systemverilog" for item in library) else "v"
        files = generate_files(document, library, language=language)
        base = workspace.path(base_dir)
        sources = sorted({(base / source.path).resolve() for item in library for source in (item.source, *item.additional_sources)})
        result = run_checks(files, sources, f"{document['name']}_wrapper", workspace_root=ROOT)
        unexpected = unexpected_generated_warnings(name, files, result["diagnostics"])
        result["generated_warning_policy"] = {"unexpected": len(unexpected),
            "exemptions": [item for item in result["diagnostics"] if item["severity"] == "warning"
                           and item["location"].get("file") in files and item not in unexpected]}
        if unexpected:
            result["valid"] = False
            result["diagnostics"].extend({**item, "code": "HDL_GENERATED_WARNING", "severity": "error",
                                          "message": MESSAGES["HDL_GENERATED_WARNING"].format(**item["params"])} for item in unexpected)
        results.append({"case": name, **result})
        output.write_text(json.dumps({"schema_version": 2, "results": results}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        errors = sum(item["severity"] == "error" for item in result["diagnostics"])
        warnings = sum(item["severity"] == "warning" for item in result["diagnostics"])
        cells = next((tool.get("cell_count") for tool in result["tools"] if tool["name"] == "yosys"), None)
        print(json.dumps({"case": name, "valid": result["valid"], "errors": errors, "warnings": warnings, "synthesis_cells": cells}), flush=True)
    return 0 if all(item["valid"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())