import json

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