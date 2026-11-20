import json
import hashlib
import re

from core.design import DesignFormatError, check_document
from core.diagnostics import Diagnostic
from core.persistence import canonical_document
from core.semantic import inspect_design


def generate_files(document, library):
    check_document(document)
    ordered = json.loads(json.dumps(canonical_document(document), sort_keys=True, ensure_ascii=False, allow_nan=False))
    result = inspect_design(ordered, library)
    if not result["valid"]:
        diagnostic = next(item for item in result["diagnostics"] if item["severity"] == "error")
        raise DesignFormatError(Diagnostic(**diagnostic))
    header = ("// AUTO-GENERATED - DO NOT EDIT\n"
              f"// Design: {ordered['name']}; schema_version: {ordered['schema_version']}\n\n")
    return {name: header + result["files"][name] for name in sorted(result["files"])}


def generate_artifacts(document, library):
    files = generate_files(document, library)
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
            nets = {item["name"] for item in scope["nets"]}
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
                        records.append({"start_line": ordinal, "end_line": ordinal, "location": {"design": scope["name"], "net": name}})
        mapped[filename] = {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "ranges": records}
    return {"files": files, "source_map": {"schema_version": 1, "design": document["name"], "files": mapped}}