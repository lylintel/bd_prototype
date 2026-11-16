from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from threading import RLock
from time import monotonic
from uuid import uuid4

import bdtool
from bdip import migrate_legacy_modules
from bdsemantic import canvas_document, prepare
from core.design import DesignFormatError, check_document
from core.diagnostics import Diagnostic
from core.ops import OperationError, apply_ops, decode_endpoint, typed_endpoint, validate_operations
from core.resolve import resolve
from core.semantic import inspect_design


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def fail(code, **params):
    raise DesignFormatError(Diagnostic(code=code, severity="error", location={}, message=code, params=params))


def prepare_context(workspace, raw, base_dir):
    document, local = prepare(workspace, raw, base_dir)
    check_document(document)
    base = workspace.path(base_dir)
    published = workspace.ip_library().metadata_snapshot(base_dir=base)
    metadata = {(item.id, item.version): item for item in published}
    for item in local:
        key = (item.id, item.version)
        if key in metadata and metadata[key].to_dict() != item.to_dict():
            fail("AI_LIBRARY_CONFLICT", ip=item.id, version=item.version)
        metadata[key] = item
    catalog = workspace.path("src/ip_catalog.json")
    if catalog.is_file():
        legacy = json.loads(catalog.read_text(encoding="utf-8"), object_pairs_hook=bdtool._unique_keys)
        known = {item.id for item in metadata.values()}
        for item in migrate_legacy_modules(legacy, catalog.parent, workspace_root=workspace.root).values():
            if item.id in known:
                continue
            def relocated(source):
                return replace(source, path=Path(os.path.relpath(catalog.parent / source.path, base)).as_posix())
            item = replace(item, source=relocated(item.source), additional_sources=tuple(relocated(source) for source in item.additional_sources), base_dir=base)
            metadata[(item.id, item.version)] = item
    return document, tuple(metadata[key] for key in sorted(metadata))


def compact_design(document, library):
    resolved = resolve(document, library)
    return {"name": document["name"], "ports": {name: shape.to_dict() for name, shape in resolved.ports.items()},
            "instances": [{"name": item["name"], "ip": item["ip"], "params": item.get("params", {}),
                           "resolved_params": resolved.instances[item["name"]].parameters if item["name"] in resolved.instances else {},
                           "ports": {name: shape.to_dict() for name, shape in resolved.instances[item["name"]].ports.items()}
                           if item["name"] in resolved.instances else {}} for item in document["instances"]],
            "nets": deepcopy(document["nets"])}


def metadata_card(metadata):
    return {"id": metadata.id, "version": metadata.version,
            "parameters": [parameter.to_dict() for parameter in metadata.parameters],
            "ports": [port.to_dict() for port in metadata.ports]}


def _view(document, library, errors=()):
    result = inspect_design(document, library)
    diagnostics = [item.to_dict() for item in errors]
    diagnostics.extend(item for item in result["diagnostics"] if item not in diagnostics)
    result["diagnostics"] = diagnostics
    result["valid"] = not any(item["severity"] == "error" for item in diagnostics)
    if not result["valid"]:
        result["files"] = {}
    references = {(item["ip"]["id"], item["ip"]["version"]) for item in document["instances"]}
    references.update((item["id"], item["version"]) for item in document.get("project_ips", []))
    visible = tuple(item for item in library if (item.id, item.version) in references)
    result.update(document=deepcopy(document), canvas=canvas_document(document, visible), metadata=[item.to_dict() for item in visible])
    return result


class ProposalStore:
    def __init__(self, workspace):
        self.workspace = workspace
        self.pending = {}
        self.lock = RLock()

    def _prune(self):
        expired = [identifier for identifier, item in self.pending.items() if monotonic() - item["created"] > 600]
        for identifier in expired:
            self.pending.pop(identifier, None)

    def preview(self, payload):
        base_dir = payload.get("base_dir", ".")
        document, library = prepare_context(self.workspace, payload.get("design"), base_dir)
        operations = deepcopy(validate_operations(payload.get("ops")))
        candidate, errors = apply_ops(document, library, operations)
        result = _view(candidate, library, errors)
        summary = payload.get("summary", "")
        if not isinstance(summary, str) or len(summary) > 8000:
            fail("AI_REQUEST", field="summary")
        identifier = str(uuid4())
        result.update(id=identifier, ops=operations, summary=summary, assumptions=[], questions=[], missing_ip=[],
                      base_hash=fingerprint(document), requires_confirmation=True)
        stored = {"base_hash": result["base_hash"], "library_hash": fingerprint([item.to_dict() for item in library]),
                  "base_dir": self.workspace.relative(self.workspace.path(base_dir)) or ".", "ops": deepcopy(operations),
                  "created": monotonic(), "valid": result["valid"]}
        with self.lock:
            self._prune()
            while len(self.pending) >= 32:
                self.pending.pop(next(iter(self.pending)))
            self.pending[identifier] = stored
        return result

    def accept(self, payload):
        if payload.get("confirmed") is not True:
            fail("AI_CONFIRM_REQUIRED")
        identifier = payload.get("proposal_id")
        with self.lock:
            self._prune()
            stored = self.pending.get(identifier) if isinstance(identifier, str) else None
            if stored is None:
                fail("AI_STALE_PROPOSAL")
            if not stored["valid"]:
                fail("AI_INVALID_PROPOSAL")
            selected = payload.get("selected")
            if (not isinstance(selected, list) or not selected or any(type(index) is not int or not 0 <= index < len(stored["ops"]) for index in selected)
                    or len(selected) != len(set(selected))):
                fail("AI_SELECTION")
            base_dir = payload.get("base_dir", ".")
            document, library = prepare_context(self.workspace, payload.get("design"), base_dir)
            if (fingerprint(document) != stored["base_hash"] or fingerprint([item.to_dict() for item in library]) != stored["library_hash"]
                    or (self.workspace.relative(self.workspace.path(base_dir)) or ".") != stored["base_dir"]):
                fail("AI_STALE_PROPOSAL")
            operations = [operation for index, operation in enumerate(stored["ops"]) if index in set(selected)]
            candidate, errors = apply_ops(document, library, operations)
            result = _view(candidate, library, errors)
            if not result["valid"]:
                fail("AI_INVALID_PROPOSAL", diagnostics=[{"code": item["code"], "params": item["params"]} for item in result["diagnostics"]])
            self.pending.pop(identifier)
            return {**result, "accepted": True}

    def discard(self, payload):
        identifier = payload.get("proposal_id")
        if not isinstance(identifier, str):
            fail("AI_REQUEST", field="proposal_id")
        with self.lock:
            self.pending.pop(identifier, None)
        return {"discarded": True}


def _legacy_endpoint(text):
    if not isinstance(text, str):
        raise OperationError("OP_LEGACY_UNSUPPORTED", op="endpoint")
    if text.startswith("@"):
        return {"type": "port", "ext": text[1:]}
    parts = text.split(".")
    if len(parts) != 2:
        raise OperationError("OP_LEGACY_UNSUPPORTED", op="endpoint")
    return {"type": "port", "inst": parts[0], "port": parts[1]}


def translate_legacy(workspace, context, operations):
    document, library = prepare_context(workspace, context.get("document", context["design"]), context["base_dir"])
    translated = []
    for operation in operations:
        kind = operation["op"]
        if kind == "set_parameter":
            batch = [{"op": "set_param", "inst": operation["instance"], "name": operation["parameter"], "value": operation["value"]}]
        elif kind == "add_instance":
            choices = [item for item in library if item.id == operation["module"]]
            if len(choices) != 1:
                raise OperationError("OP_UNKNOWN_IP", ip=operation["module"], version="", reason="missing" if not choices else "ambiguous")
            batch = [{"op": "add_instance", "name": operation["name"], "ip": choices[0].id, "version": choices[0].version,
                      "params": deepcopy(operation.get("parameters", {}))}]
        elif kind == "add_port":
            shape = bdtool._ports({operation["name"]: operation["port"]}, {}, "legacy.port")[operation["name"]]
            batch = [{"op": "add_external_port", "name": operation["name"], "dir": "in" if shape.direction == "input" else "out",
                      "width": str(shape.width), "signed": shape.signed, **({"range": list(shape.bounds)} if shape.bounds is not None else {})}]
        elif kind == "connect":
            batch = [{"op": "connect", "from": _legacy_endpoint(operation["source"]), "to": _legacy_endpoint(target), "net": operation["net"]}
                     for target in operation["targets"]]
        elif kind == "remove_instance":
            batch = [{"op": kind, "name": operation["name"]}]
        elif kind == "disconnect":
            endpoint = decode_endpoint(_legacy_endpoint(operation["endpoint"]))
            batch = []
            for net in resolve(document, library).nets:
                for selected in net.endpoints:
                    if selected.raw != endpoint or len(net.drivers) != 1:
                        continue
                    targets = net.sinks if selected.drives else (selected,)
                    batch.extend({"op": "disconnect", "from": typed_endpoint(net.drivers[0].raw), "to": typed_endpoint(target.raw), "net": net.name} for target in targets)
            if not batch:
                raise OperationError("OP_NOT_CONNECTED")
        else:
            raise OperationError("OP_LEGACY_UNSUPPORTED", op=kind)
        candidate, errors = apply_ops(document, library, batch)
        structural = next((item for item in errors if item.code.startswith("OP_")), None)
        if structural:
            raise OperationError(structural.code, **structural.params)
        document = candidate
        translated.extend(batch)
    validate_operations(translated)
    return translated