import json
import hashlib
import re

from core.design import DesignFormatError, check_document
from core.diagnostics import Diagnostic
from core.persistence import canonical_document
from core.semantic import inspect_design
from bdip import MESSAGES


def _generated(document, library, language):
    if language not in ("v", "sv"):
        raise ValueError(MESSAGES["HDL_LANGUAGE"])
    check_document(document)
    source, origins = document, {}
    if document.get("schema_version") == 5:
        from core.interfaces import expand_interfaces
        expanded = expand_interfaces(document, library)
        if expanded["diagnostics"]:
            raise DesignFormatError(expanded["diagnostics"][0])
        source, origins = expanded["document"], expanded["origins"]
    ordered = json.loads(json.dumps(canonical_document(source), sort_keys=True, ensure_ascii=False, allow_nan=False))
    result = inspect_design(ordered, library)
    if not result["valid"]:
        diagnostic = next(item for item in result["diagnostics"] if item["severity"] == "error")
        raise DesignFormatError(Diagnostic(**diagnostic))
    version = 5 if any(origins.values()) else ordered["schema_version"]
    header = ("// AUTO-GENERATED - DO NOT EDIT\n"
              f"// Design: {ordered['name']}; schema_version: {version}\n"
              "`timescale 1ns/1ps\n\n")
    files = {name: header + result["files"][name] for name in sorted(result["files"])}
    if language == "sv":
        files = {name.removesuffix(".v") + ".sv": re.sub(r"^(\s*(?:(?:input|output)\s+)?)wire\b", r"\1logic", text, flags=re.MULTILINE)
                 for name, text in files.items()}
    return files, origins


def generate_files(document, library, *, language="v"):
    return _generated(document, library, language)[0]


def generate_artifacts(document, library, *, language="v"):
    files, origins = _generated(document, library, language)
    scopes = {document["name"]: document, **document.get("subdesigns", {})}
    mapped = {}
    for filename, text in files.items():
        scope = scopes.get(filename.rsplit(".", 1)[0])
        lines = text.splitlines()
        records = []
        if scope is None:
            records.append({"start_line": 1, "end_line": len(lines), "location": {"design": document["name"]}})
        else:
            instances = {item["name"] for item in scope["instances"]}
            members = origins.get(scope["name"], {})
            nets = {item["name"] for item in scope["nets"]} | members.keys()
            block_start = 1
            for ordinal, line in enumerate(lines, 1):
                if not line.strip():
                    block_start = ordinal + 1
                instance = re.match(r"^    (?:\) |[A-Za-z_][A-Za-z0-9_$]* )([A-Za-z_][A-Za-z0-9_$]*) \(", line)
                if instance and instance[1] in instances:
                    end = next((index for index in range(ordinal, len(lines) + 1) if lines[index - 1].strip().endswith(");")), ordinal)
                    records.append({"start_line": block_start, "end_line": end, "location": {"design": scope["name"], "instance": instance[1]}})
                if line.startswith(("    wire ", "    logic ", "    assign ")):
                    for name in sorted(nets.intersection(re.findall(r"[A-Za-z_][A-Za-z0-9_$]*", line))):
                        records.append({"start_line": ordinal, "end_line": ordinal, "location": {"design": scope["name"], "net": name, **members.get(name, {})}})
        mapped[filename] = {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "ranges": records}
    return {"files": files, "source_map": {"schema_version": 2 if any(origins.values()) else 1, "design": document["name"], "files": mapped}}