from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import bdtool
from bdip import IpMetadata, migrate_legacy_modules
from core.design import DesignFormatError, check_document, migrate
from core.diagnostics import issue
from core.resolve import ParameterError, parameters
from core.semantic import inspect_design


def prepare(workspace, document, base_dir):
    base = workspace.path(base_dir)
    if not isinstance(document, dict):
        raise DesignFormatError(issue("D001", {}, reason="object"))
    if "schema_version" not in document:
        workspace.structure(document)
        workspace.sources(document, base)
        project = tuple(migrate_legacy_modules(document, base, workspace_root=workspace.root).values())
        ids = {metadata.id for metadata in project}
    else:
        if document.get("schema_version") not in (2, 3):
            raise DesignFormatError(issue("D001", {}, reason="schema_version"))
        raw_project = document.get("project_ips", [])
        if not isinstance(raw_project, list) or len(raw_project) > 200:
            raise DesignFormatError(issue("D001", {}, reason="project_ips"))
        project = tuple(IpMetadata.from_dict(item, base_dir=base) for item in raw_project)
        ids = {metadata.id for metadata in project}
        for instance in document.get("instances", []) if isinstance(document.get("instances"), list) else []:
            if isinstance(instance, dict) and isinstance(instance.get("ip"), dict) and isinstance(instance["ip"].get("id"), str):
                ids.add(instance["ip"]["id"])
    published = workspace.ip_library().metadata_snapshot(ids, base_dir=base)
    library = list(published)
    seen_project = set()
    for metadata in project:
        key = (metadata.id, metadata.version)
        if key in seen_project:
            raise DesignFormatError(issue("E005", {}, ip=metadata.id, version=metadata.version, reason="ambiguous", candidates=[metadata.version]))
        seen_project.add(key)
        for source in (metadata.source, *metadata.additional_sources):
            path = (base / source.path).resolve()
            if (not path.is_relative_to(workspace.root) or not path.is_file() or path.stat().st_size > 1024 * 1024
                    or hashlib.sha256(path.read_bytes()).hexdigest() != source.sha256):
                raise DesignFormatError(issue("D005", {"module": metadata.id}, reason="source"))
        candidates = [item for item in published if item.id == metadata.id]
        if "schema_version" not in document:
            if candidates and any(item.source.sha256 != metadata.source.sha256 for item in candidates):
                raise DesignFormatError(issue("E005", {"module": metadata.id}, ip=metadata.id, version="", reason="definition_conflict", candidates=[item.version for item in candidates]))
            if not candidates:
                library.append(metadata)
        else:
            exact = [item for item in candidates if item.version == metadata.version]
            if exact and exact[0].to_dict() != metadata.to_dict():
                raise DesignFormatError(issue("E005", {"module": metadata.id}, ip=metadata.id, version=metadata.version, reason="definition_conflict", candidates=[item.version for item in exact]))
            if not exact:
                library.append(metadata)
    prepared = migrate(document, library) if "schema_version" not in document else deepcopy(document)
    return prepared, tuple(library)


def _canvas_pins(endpoint, depth=0):
    if not isinstance(endpoint, dict) or depth > 16:
        return []
    if "inst" in endpoint and "port" in endpoint:
        return [f"{endpoint['inst']}.{endpoint['port']}"]
    if "ext" in endpoint:
        return [f"@{endpoint['ext']}"]
    if isinstance(endpoint.get("concat"), list):
        return [pin for child in endpoint["concat"][:128] for pin in _canvas_pins(child, depth + 1)]
    return []


def canvas_document(document, library):
    modules = {}
    for metadata in library:
        try:
            values = parameters(metadata, {})
        except ParameterError:
            values = {parameter.name: parameter.default for parameter in metadata.parameters}
        modules[metadata.id] = {"sources": [source.path for source in (metadata.source, *metadata.additional_sources)],
            "parameters": {parameter.name: {"default": values[parameter.name],
                           **{key: value for key, value in parameter.to_dict().items() if key in {"min", "max"}}} for parameter in metadata.parameters},
            "ports": {port.name: {"direction": "input" if port.dir == "in" else "output", "signed": bool(port.signed),
                      **({"range": list(port.range)} if port.range is not None else {})} for port in metadata.ports}}
    instances = {}
    for item in document.get("instances", []):
        if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("ip"), dict):
            module = item["ip"].get("id", "")
            modules.setdefault(module, {"sources": [], "parameters": {}, "ports": {}})
            instances[item["name"]] = {"module": module, "parameters": deepcopy(item.get("params", {}))}
    nets = {}
    for item in document.get("nets", []):
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            nets[item["name"]] = list(dict.fromkeys(pin for endpoint in item.get("endpoints", []) for pin in _canvas_pins(endpoint)))
    return {"name": document.get("name", ""), "modules": modules, "instances": instances,
            "ports": deepcopy(document.get("ports", {})), "nets": nets}


def inspect_workspace(workspace, document, base_dir):
    try:
        prepared, library = prepare(workspace, document, base_dir)
        result = inspect_design(prepared, library)
        result.update(document=prepared, canvas=canvas_document(prepared, library), metadata=[metadata.to_dict() for metadata in library])
        return result
    except (bdtool.DesignError, DesignFormatError, OSError, ValueError, TypeError, KeyError) as error:
        diagnostic = error.diagnostic if isinstance(error, DesignFormatError) else issue("D005", {}, reason=getattr(error, "code", "source_or_metadata"))
        return {"valid": False, "diagnostics": [diagnostic.to_dict()], "files": {}, "parameters": {},
                "interfaces": {"ports": {}, "instances": {}}}


def save_document(workspace, payload):
    from bdgui import check_layout

    document, library = prepare(workspace, payload.get("design"), payload.get("base_dir", "."))
    check_document(document)
    target = workspace.path(payload.get("path", ""))
    if not target.is_relative_to(workspace.path("designs")) or target.suffix != ".json" or target.name.endswith(".layout.json"):
        raise DesignFormatError(issue("D005", {}, reason="save_path"))
    base = workspace.path(payload.get("base_dir", "."))
    sources = set()
    snapshots = []
    for metadata in library:
        raw = metadata.to_dict()
        for source in [raw["source"], *raw.get("additional_sources", [])]:
            path = (base / source["path"]).resolve()
            sources.add(path)
            source["path"] = Path(os.path.relpath(path, target.parent)).as_posix()
        snapshots.append(raw)
    document["project_ips"] = snapshots
    check_document(document)
    layout = check_layout(payload.get("layout", {}))
    bdtool._write_outputs({target.name: json.dumps(document, indent=2, ensure_ascii=False) + "\n",
                           target.with_suffix(".layout.json").name: json.dumps(layout, indent=2) + "\n"}, target.parent, sources)
    return workspace.load(workspace.relative(target))


def generate_document(workspace, payload):
    document, library = prepare(workspace, payload.get("design"), payload.get("base_dir", "."))
    result = inspect_design(document, library)
    if not result["valid"]:
        raise bdtool.DesignError(result["diagnostics"][0]["message"])
    base = workspace.path(payload.get("base_dir", "."))
    sources = {(base / source.path).resolve() for metadata in library for source in (metadata.source, *metadata.additional_sources)}
    output = workspace.path("build/gui")
    bdtool._write_outputs(result["files"], output, sources)
    return {"files": result["files"], "paths": [workspace.relative(output / name) for name in result["files"]]}