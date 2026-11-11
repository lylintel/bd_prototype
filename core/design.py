from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from bdip import IpMetadata, IpMetadataError, _legacy_width
from core.diagnostics import Diagnostic, issue


MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "design.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)


class DesignFormatError(ValueError):
    def __init__(self, diagnostic: Diagnostic):
        self.diagnostic = diagnostic
        super().__init__(diagnostic.message)


def _invalid(path: str, reason: str) -> DesignFormatError:
    return DesignFormatError(issue("D001", {"path": path}, reason=reason))


def check_document(document: object) -> None:
    try:
        if len(json.dumps(document, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise _invalid("$", "size")
        error = next(VALIDATOR.iter_errors(document), None)
        if error is not None:
            path = "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.absolute_path)
            raise _invalid(path, str(error.validator))
        for index, metadata in enumerate(document.get("project_ips", [])):
            try:
                IpMetadata.from_dict(metadata)
            except IpMetadataError as error:
                raise _invalid(f"$.project_ips[{index}]", error.code) from error
    except (TypeError, RecursionError, UnicodeError, OverflowError) as error:
        raise _invalid("$", "json") from error
    except ValueError as error:
        if isinstance(error, DesignFormatError):
            raise
        raise _invalid("$", "json") from error


def load_document(text: str) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise _invalid("$", "duplicate_key")
            result[key] = value
        return result

    def nonfinite(value):
        raise _invalid("$", "nonfinite")

    try:
        if len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise _invalid("$", "size")
        result = json.loads(text, object_pairs_hook=unique, parse_constant=nonfinite)
        if not isinstance(result, dict):
            raise _invalid("$", "object")
        return result
    except (TypeError, UnicodeError, RecursionError, json.JSONDecodeError) as error:
        raise _invalid("$", "json") from error


def migrate(document: dict, library: tuple[IpMetadata, ...] | list[IpMetadata]) -> dict:
    if not isinstance(document, dict):
        raise _invalid("$", "object")
    if "schema_version" in document:
        check_document(document)
        return deepcopy(document)
    if set(document) != {"name", "modules", "ports", "instances", "nets"}:
        raise _invalid("$", "fields")
    if not all(isinstance(document[key], dict) for key in ("modules", "ports", "instances", "nets")):
        raise _invalid("$", "object")
    by_id = {}
    for metadata in library:
        by_id.setdefault(metadata.id, []).append(metadata)
    instances, selected = [], {}
    for name, item in document["instances"].items():
        if not isinstance(item, dict) or set(item) - {"module", "parameters"} or not isinstance(item.get("module"), str):
            raise _invalid(f"$.instances.{name}", "fields")
        candidates = by_id.get(item["module"], [])
        if len(candidates) != 1:
            raise DesignFormatError(issue("E005", {"instance": name}, ip=item["module"], version="",
                                          reason="missing" if not candidates else "ambiguous",
                                          candidates=[candidate.version for candidate in candidates]))
        metadata = candidates[0]
        selected[(metadata.id, metadata.version)] = metadata
        instances.append({"name": name, "ip": {"id": metadata.id, "version": metadata.version},
                          "params": deepcopy(item.get("parameters", {}))})
    for name, definition in document["modules"].items():
        candidates = by_id.get(name, [])
        if len(candidates) != 1:
            raise DesignFormatError(issue("E005", {"module": name}, ip=name, version="",
                                          reason="missing" if not candidates else "ambiguous",
                                          candidates=[candidate.version for candidate in candidates]))
        metadata = candidates[0]
        compatible = isinstance(definition, dict) and isinstance(definition.get("ports"), dict)
        if compatible:
            ports = definition["ports"]
            compatible = set(ports) == {port.name for port in metadata.ports}
            for port in metadata.ports:
                previous = ports.get(port.name, {})
                compatible = compatible and isinstance(previous, dict) and (
                    previous.get("direction") == {"in": "input", "out": "output"}.get(port.dir)
                    and previous.get("range") == (list(port.range) if port.range is not None else None)
                    and bool(previous.get("signed", False)) == bool(port.signed)
                    and _legacy_width(previous.get("range")) == port.width)
            expected = {parameter.name: {"default": parameter.default,
                        **{key: value for key, value in parameter.to_dict().items() if key in {"min", "max"}}}
                        for parameter in metadata.parameters}
            previous_parameters = definition.get("parameters", {})
            compatible = compatible and isinstance(previous_parameters, dict) and expected == {
                key: {**value, "default": str(value.get("default"))} for key, value in previous_parameters.items()
                if isinstance(value, dict)}
        if not compatible:
            raise DesignFormatError(issue("E005", {"module": name}, ip=name, version=metadata.version,
                                          reason="definition_conflict", candidates=[metadata.version]))
        selected[(metadata.id, metadata.version)] = metadata
    nets = []
    for name, endpoints in document["nets"].items():
        if not isinstance(endpoints, list):
            raise _invalid(f"$.nets.{name}", "array")
        converted = []
        for endpoint in endpoints:
            if not isinstance(endpoint, str):
                raise _invalid(f"$.nets.{name}", "endpoint")
            if endpoint.startswith("@"):
                converted.append({"ext": endpoint[1:]})
            elif endpoint.count(".") == 1:
                instance, port = endpoint.split(".")
                converted.append({"inst": instance, "port": port})
            else:
                raise _invalid(f"$.nets.{name}", "endpoint")
        nets.append({"name": name, "endpoints": converted})
    result = {"schema_version": 2, "name": document["name"], "ports": deepcopy(document["ports"]),
              "instances": instances, "nets": nets, "project_ips": [item.to_dict() for item in selected.values()]}
    check_document(result)
    return result